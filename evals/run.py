"""Run eval tasks: k trials per task, each graded as soon as it is recorded.

See docs/eval-architecture.md#running-the-evals. Run: uv run python -m evals.run --part abstain
A part that calls the model or web search needs the API keys: uv run --env-file .env python -m ...
"""

import argparse
import copy
import datetime as dt
import json
import traceback
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from unittest import mock

from langchain_core.callbacks import get_usage_metadata_callback
from pydantic_core import to_jsonable_python

import out_of_frame.finding
import out_of_frame.investigation
import out_of_frame.prompt_injection
import out_of_frame.report
import out_of_frame.triage
from evals.graders.finding import Expected, Grade, grade_grounding, grade_result
from evals.graders.input_loop import grade_property
from evals.graders.prompt_injection import grade_flagged
from evals.graders.report import grade_citations, grade_distances
from evals.load import EVALS, FIXTURES, Conversation, Inputs, Task, load, load_all
from out_of_frame import agent, geocoding, prices
from out_of_frame.config import MODEL
from out_of_frame.grounding import collect_cited_page, find_grounding_errors
from out_of_frame.prices import compute_run_cost
from out_of_frame.state import (
    Coordinates,
    Finding,
    InvestigationState,
    MapObject,
    RunState,
    Source,
)
from out_of_frame.web_search import (
    MeteredWebSearch,
    PageText,
    TavilyWebSearch,
    WebSearch,
    WebSearchAccessError,
)

RESULTS = EVALS / "results"


@dataclass(frozen=True)
class Outcome:
    """The state where the suite ends."""

    finding: Finding
    sources: list[Source]  # the snippet or page that the finding cites, if any


@dataclass(frozen=True)
class Trial:
    """What a part returns. The harness counts the tool calls and the cost itself."""

    # bool: whether the injection check flagged the page; str: a report's draft; RunState: the
    # input state where the input loop ends
    outcome: Outcome | bool | str | RunState
    transcript: list[dict]  # for a person who looks into a failure; no grader reads it


class NoWebSearch:
    """The web search of a run without one: only the investigate part searches, so a part that
    searches anyway fails its trial."""

    def search(self, query: str) -> list[PageText]:
        raise RuntimeError("this run has no web search")

    def extract(self, url: str) -> list[PageText]:
        raise RuntimeError("this run has no web search")


# The part of the agent a suite runs. It gets only the task's inputs, the date and web search.
type Part = Callable[[Inputs, dt.date, WebSearch], Trial]


def abstain(inputs: Inputs, date: dt.date, web_search: WebSearch) -> Trial:
    """A stub that never identifies anything."""
    return Trial(Outcome(Finding.unidentified(find_map_object(inputs).id), []), transcript=[])


def trust_every_page(inputs: Inputs, date: dt.date, web_search: WebSearch) -> Trial:
    """A stub injection check that never flags a page."""
    return Trial(False, transcript=[])


def check_page(inputs: Inputs, date: dt.date, web_search: WebSearch) -> Trial:
    """The prompt injection check, on one snippet or page."""
    if not isinstance(inputs, PageText):
        raise TypeError("check_page needs a task with a page")
    [flagged] = out_of_frame.prompt_injection.flag_injections([inputs])
    return Trial(flagged, transcript=[])


def draft_finding(inputs: Inputs, date: dt.date, web_search: WebSearch) -> Trial:
    """The model call that drafts the finding, on a task from a written state."""
    if not isinstance(inputs, InvestigationState):
        raise TypeError("draft_finding needs a task from a written state")
    finding = out_of_frame.finding.draft_finding(inputs, date)
    return Trial(Outcome(finding, []), transcript=[])


def investigate(inputs: Inputs, date: dt.date, web_search: WebSearch) -> Trial:
    """The investigation subgraph on one map object. The transcript has each step's update, so
    that a finding that the grounding check replaced can still be read, with the reasons."""
    if not isinstance(inputs, MapObject):
        raise TypeError("investigate needs a task with a map object")
    start = InvestigationState(map_object=inputs, history=[], pages=[], finding=None)
    context = out_of_frame.investigation.Context(date, web_search)
    steps = out_of_frame.investigation.build_graph().stream(
        start, context=context, stream_mode=["updates", "values"]
    )
    transcript: list[dict] = []
    end: dict | InvestigationState = start
    draft: Finding | None = None
    for mode, chunk in steps:
        assert isinstance(chunk, dict)  # an update by node name, or the whole state
        if mode == "values":
            end = chunk
            continue
        transcript.append(to_jsonable_python(chunk))
        if written := chunk.get("write_finding"):
            draft = written["finding"]
    state = InvestigationState.model_validate(end)
    assert state.finding is not None  # every path through the subgraph ends with a finding
    if draft is not None and draft != state.finding:
        errors = find_grounding_errors(draft, state.map_object, state.pages)
        transcript.append({"find_grounding_errors": errors})
    cited = collect_cited_page(state.finding.evidence_id, state.pages)
    return Trial(Outcome(state.finding, cited), transcript)


def triage_object(inputs: Inputs, date: dt.date, web_search: WebSearch) -> Trial:
    """One triage call on one map object. An object that triage sends to investigation is
    graded as unidentified: triage leaves it to the web. The transcript has the model's answer,
    or null if it was cut off or does not parse, so that a person can tell the two apart."""
    if not isinstance(inputs, MapObject):
        raise TypeError("triage_object needs a task with a map object")
    answer = out_of_frame.triage.ask(inputs)
    finding = out_of_frame.triage.settle(inputs, answer) or Finding.unidentified(inputs.id)
    transcript = [{"answer": answer.model_dump() if answer is not None else None}]
    return Trial(Outcome(finding, []), transcript)


def write_report(inputs: Inputs, date: dt.date, web_search: WebSearch) -> Trial:
    """The report's draft, on a task from a written run state, before code fills in its
    references."""
    if not isinstance(inputs, RunState):
        raise TypeError("write_report needs a task from a written run state")
    return Trial(out_of_frame.report.write_report(inputs, date), transcript=[])


class UnrecordedRequestError(LookupError):
    """The agent geocoded a text that the input loop task has no recorded response for."""


def run_input_loop(inputs: Inputs, date: dt.date, web_search: WebSearch) -> Trial:
    """The input loop until the input is complete, with the task's replies in turn, on the
    task's recorded Nominatim responses. A request with no recorded response, or a question
    after the replies have run out, ends the trial where the agent stopped, with an input that
    is not complete, so that its grade fails. The transcript is the conversation, with the
    reason it ended early."""
    if not isinstance(inputs, Conversation):
        raise TypeError("run_input_loop needs an input loop task")
    recorded = {source.request: FIXTURES / source.fixture for source in inputs.sources}

    def replay(text: str) -> list[dict]:
        if text not in recorded:
            raise UnrecordedRequestError(f"no recorded Nominatim response for {text!r}")
        return json.loads(recorded[text].read_text(encoding="utf-8"))

    graph, config = agent.build_graph(), agent.start_thread()
    failure = None
    with mock.patch.object(geocoding, "call_nominatim", replay):
        try:
            agent.run(inputs.messages, date, web_search, input_only=True, config=config)
        except (agent.UnansweredQuestionError, UnrecordedRequestError) as error:  # its failure
            failure = repr(error)
    state = RunState.model_validate(graph.get_state(config).values)
    transcript: list[dict] = [message.model_dump() for message in state.messages]
    if failure is not None:
        transcript.append({"failure": failure})
    return Trial(state, transcript)


PARTS: dict[str, Part] = {
    "abstain": abstain,
    "trust_every_page": trust_every_page,
    "check_page": check_page,
    "draft_finding": draft_finding,
    "investigate": investigate,
    "triage_object": triage_object,
    "write_report": write_report,
    "run_input_loop": run_input_loop,
}
# The suites that each part can run.
PART_SUITES = {
    "abstain": {"finding", "live investigation", "triage"},
    "trust_every_page": {"injection check"},
    "check_page": {"injection check"},
    "draft_finding": {"finding"},
    "investigate": {"live investigation"},
    "triage_object": {"triage"},
    "write_report": {"report"},
    "run_input_loop": {"input loop"},
}


def find_map_object(inputs: Inputs) -> MapObject:
    if isinstance(inputs, PageText | RunState | Conversation):
        raise TypeError("an injection check, report or input loop task has no one map object")
    return inputs if isinstance(inputs, MapObject) else inputs.map_object


def select_graded_sources(task: Task, outcome: Outcome) -> list[Source]:
    """A task from a written state is graded against its own pages only, so the agent cannot add
    or change evidence. A live task is graded against the page the agent stored for its
    finding."""
    if isinstance(task.inputs, InvestigationState):
        return task.inputs.pages
    return outcome.sources


def grade(task: Task, outcome: Outcome | bool | str | RunState) -> list[Grade]:
    expected = task.expected
    if isinstance(outcome, RunState) and isinstance(expected, Coordinates):
        return [grade_property(outcome, expected)]
    if isinstance(outcome, str) and isinstance(task.inputs, RunState):
        return [grade_citations(outcome, task.inputs), grade_distances(outcome, task.inputs)]
    if isinstance(outcome, bool) and isinstance(expected, bool):
        return [grade_flagged(outcome, expected)]
    if isinstance(outcome, Outcome) and isinstance(expected, Expected):
        map_object = find_map_object(task.inputs)
        return [
            grade_result(outcome.finding, map_object, expected),
            grade_grounding(outcome.finding, map_object, select_graded_sources(task, outcome)),
        ]
    raise TypeError(f"{task.id}: the part's outcome does not fit the task's expected result")


def dump_outcome(task: Task, outcome: Outcome | bool | str | RunState) -> dict:
    if isinstance(outcome, RunState):
        return {"property": outcome.property and outcome.property.model_dump(mode="json")}
    if isinstance(outcome, bool):
        return {"flagged": outcome}
    if isinstance(outcome, str):
        return {"draft": outcome}
    return {
        "finding": outcome.finding.model_dump(mode="json"),
        # The sources the finding is graded against, so that the grade can be checked later.
        "sources": [s.model_dump(mode="json") for s in select_graded_sources(task, outcome)],
    }


def run_task(
    task: Task, part: Part, k: int, record: Callable[[dict], None], web_search: WebSearch | None
) -> list[dict]:
    trials = []
    for n in range(1, k + 1):
        date = task.date or dt.date.today()
        metered = MeteredWebSearch(web_search or NoWebSearch())
        trial, error = None, None
        with get_usage_metadata_callback() as usage:
            try:
                trial = part(copy.deepcopy(task.inputs), date, metered)  # a clean state
            except WebSearchAccessError:
                raise  # every other trial would fail the same way
            except Exception:
                error = traceback.format_exc()
        counts = {
            "tool_calls": metered.tool_calls,
            "cost_usd": compute_run_cost(usage.usage_metadata, metered.credits),
        }
        if trial is None:
            failed = {
                "task": task.id,
                "trial": n,
                "date": date.isoformat(),
                "error": error,
                **counts,
                "passed": False,
                "grades": [],
            }
            record(failed)
            trials.append(failed)
            continue
        recorded = {
            "task": task.id,
            "trial": n,
            "date": date.isoformat(),
            **dump_outcome(task, trial.outcome),
            "transcript": trial.transcript,
            **counts,
        }
        record(recorded)  # before grading, so that a grader failure does not lose the trial
        grades = grade(task, trial.outcome)
        graded = {
            "task": task.id,
            "trial": n,
            "passed": all(g.passed for g in grades),
            "grades": [asdict(g) for g in grades],
        }
        record(graded)
        trials.append(recorded | graded)
    return trials


def summarise(suite: str, trials: list[dict]) -> dict:
    """A live task reports the share of trials with the right result. Any other task passes or
    fails each trial: pass@k means at least one of the k trials passed, pass^k all of them."""
    summary = {
        "trials": len(trials),
        "graders": {
            name: sum(g["passed"] for t in trials for g in t["grades"] if g["grader"] == name)
            for name in dict.fromkeys(g["grader"] for t in trials for g in t["grades"])
        },
        "errors": sum("error" in t for t in trials),  # trials where the part failed
        "tool_calls": sum(t["tool_calls"] for t in trials),
        "cost_usd": sum(t["cost_usd"] for t in trials),
    }
    if suite == "live investigation":
        summary["right result share"] = summary["graders"].get("result", 0) / len(trials)
    else:
        summary |= {
            "passed": sum(t["passed"] for t in trials),
            "pass@k": any(t["passed"] for t in trials),
            "pass^k": all(t["passed"] for t in trials),
        }
    return summary


def run(
    tasks: Iterable[Task],
    part: Part,
    k: int,
    out: Path,
    name: str | None = None,
    web_search: WebSearch | None = None,
) -> dict[str, dict]:
    """Run every task and write each trial to out at once. A cancelled run is incomplete.

    An error of the part fails its trial, and the run goes on; an error of a grader, or a
    missing or refused web search key, stops it. TODO: average pass@k and pass^k over each suite.
    """
    if k < 1:
        raise ValueError("k must be at least 1")
    if MODEL not in prices.load().models:
        raise ValueError(f"no price for {MODEL}: add it to data/prices.yaml")
    tasks = list(tasks)
    ids = [task.id for task in tasks]
    if duplicates := sorted({id for id in ids if ids.count(id) > 1}):
        raise ValueError(f"task IDs used more than once: {', '.join(duplicates)}")
    summaries, complete = {}, False
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as f:  # never overwrite an earlier run

        def record(line: dict) -> None:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
            f.flush()

        record(
            {
                "part": name or getattr(part, "__name__", repr(part)),
                "k": k,
                "started": dt.datetime.now(dt.UTC).isoformat(),
                "prices_as_of": prices.load().as_of.isoformat(),  # so that stale prices show
            }
        )
        try:
            for task in tasks:
                summaries[task.id] = summarise(
                    task.suite, run_task(task, part, k, record, web_search)
                )
            complete = True
        finally:
            record({"complete": complete, "summaries": summaries})
    return summaries


def select_tasks(part: str, paths: list[Path]) -> list[Task]:
    """The tasks in the given files, or, if none are given, every task that the part can run."""
    suites = PART_SUITES[part]
    if not paths:
        return [task for task in load_all() if task.suite in suites]
    tasks = [load(path) for path in paths]
    if others := [task.id for task in tasks if task.suite not in suites]:
        raise ValueError(f"the part {part} cannot run {', '.join(others)}")
    return tasks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "tasks", nargs="*", type=Path, help="task files; if none, every task the part can run"
    )
    parser.add_argument("--part", choices=PARTS, required=True)
    parser.add_argument("--k", type=int, default=3, help="trials per task")
    args = parser.parse_args()
    if args.k < 1:
        parser.error("--k must be at least 1")

    try:
        tasks = select_tasks(args.part, args.tasks)
        # investigate is the only part that searches
        web_search = TavilyWebSearch() if args.part == "investigate" else None
    except (ValueError, WebSearchAccessError) as error:
        parser.error(str(error))
    out = RESULTS / f"{dt.datetime.now(dt.UTC):%Y-%m-%dT%H-%M-%S-%fZ}.jsonl"
    for task_id, s in run(tasks, PARTS[args.part], args.k, out, args.part, web_search).items():
        graders = ", ".join(f"{name} {n}/{s['trials']}" for name, n in s["graders"].items())
        if "pass@k" in s:
            result = (
                f"{s['passed']}/{s['trials']} passed, pass@k {s['pass@k']}, pass^k {s['pass^k']}"
            )
        else:
            result = f"right result in {s['right result share']:.0%} of trials"
        if graders:
            result += f"; graders: {graders}"
        if s["errors"]:
            result += f"; part errors: {s['errors']}"
        result += f"; tool calls: {s['tool_calls']}, cost: ${s['cost_usd']:.4f}"
        print(f"{task_id}: {result}")
    print(f"Trials: {out}")


if __name__ == "__main__":
    main()
