"""Run eval tasks: k trials per task, each graded as soon as it is recorded.

See docs/eval-architecture.md#running-the-evals. Run: uv run python -m evals.run --part abstain
A part that calls the model or web search needs the API keys: uv run --env-file .env python -m ...
"""

import argparse
import copy
import datetime as dt
import json
import statistics
import subprocess
import traceback
from collections import Counter
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
from evals import dialogue, judge
from evals.calibrate import check_calibrated
from evals.config import JUDGE_EFFORT, JUDGE_MAX_TOKENS, JUDGE_MODEL
from evals.graders.end_to_end import (
    ExpectedRun,
    grade_findings,
    grade_journeys,
    mark_branches,
)
from evals.graders.enough import ExpectedDecision, grade_decision
from evals.graders.finding import Expected, Grade, grade_grounding, grade_result
from evals.graders.input_loop import ExpectedInput, grade_destinations, grade_property
from evals.graders.prompt_injection import grade_flagged
from evals.graders.report import grade_citations, grade_distances
from evals.load import EVALS, FIXTURES, Conversation, Inputs, Task, load, load_all
from out_of_frame import agent, geocoding, prices
from out_of_frame.config import (
    EFFORT,
    INJECTION_EFFORT,
    INJECTION_MAX_TOKENS,
    INJECTION_MODEL,
    MAX_TOKENS,
    MODEL,
)
from out_of_frame.grounding import collect_cited_page, find_grounding_errors
from out_of_frame.prices import compute_run_cost
from out_of_frame.state import (
    Finding,
    InvestigationState,
    MapObject,
    RunState,
    Source,
    ToolCall,
)
from out_of_frame.web_search import (
    MeteredWebSearch,
    PageText,
    TavilyWebSearch,
    WebSearch,
    WebSearchAccessError,
)

RESULTS = EVALS / "results"
JUDGED_PARTS = {"write_report", "run_end_to_end"}  # the parts whose reports the judges grade
JUDGES = ["interpretation", "no_verdict"]  # the judges of a whole report, beside support


@dataclass(frozen=True)
class Outcome:
    """The state where the suite ends."""

    finding: Finding
    sources: list[Source]  # the snippet or page that the finding cites, if any


@dataclass(frozen=True)
class Decision:
    """Where an Enough task ends: the tool call that the model makes, or None if it stops."""

    call: ToolCall | None


@dataclass(frozen=True)
class Trial:
    """What a part returns. The harness counts the tool calls and the cost itself."""

    # bool: whether the injection check flagged the page; str: a report's draft; RunState: the
    # state where the input loop or an end-to-end run ends
    outcome: Outcome | Decision | bool | str | RunState
    transcript: list[dict]  # for a person who looks into a failure; no grader reads it
    run: Path | None = None  # an end-to-end trial's saved run, which the judges grade


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


def decide_enough(inputs: Inputs, date: dt.date, web_search: WebSearch) -> Trial:
    """The model's decision to stop or to make one more tool call, on a task from a written
    search history. Code does not run the call."""
    if not isinstance(inputs, InvestigationState):
        raise TypeError("decide_enough needs a task from a written state")
    call = out_of_frame.investigation.choose_call(inputs, date)
    return Trial(Decision(call), transcript=[])


def investigate(inputs: Inputs, date: dt.date, web_search: WebSearch) -> Trial:
    """The investigation subgraph from its start: one map object and the kind of its source.
    The transcript has each step's update, so that a finding that the grounding check
    replaced can still be read, with the reasons."""
    if not isinstance(inputs, InvestigationState) or inputs.history:
        raise TypeError("investigate needs a live investigation task")
    start = inputs
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
            dialogue.run(
                inputs.messages,
                date,
                web_search,
                input_only=True,
                config=config,
                initial_state=inputs.initial_state,
            )
        except (dialogue.UnansweredQuestionError, UnrecordedRequestError) as error:  # its failure
            failure = repr(error)
    state = RunState.model_validate(graph.get_state(config).values)
    transcript: list[dict] = [
        {"role": "user" if message.type == "human" else "agent", "text": message.text}
        for message in state.messages
    ]
    if failure is not None:
        transcript.append({"failure": failure})
    return Trial(state, transcript)


def run_end_to_end(inputs: Inputs, date: dt.date, web_search: WebSearch) -> Trial:
    """The whole agent on live sources, from the task's first message, which completes the
    input, so a question fails the trial. The run is saved as evals/judge.py saves it, so that
    the judges can grade it, and the transcript names its file. A run that stops is saved too,
    and its error fails the trial, or stops the eval run if web search refused the key or the
    run was cancelled."""
    if not isinstance(inputs, Conversation) or len(inputs.messages) != 1 or inputs.sources:
        raise TypeError("run_end_to_end needs an end-to-end task")
    saved, error = judge.run_agent(inputs.messages[0], date, MeteredWebSearch(web_search))
    path = judge.save(saved, "run")
    if error is not None:
        error.add_note(f"The run is saved in {path}")
        raise error
    state = RunState.model_validate(saved["state"])
    return Trial(state, transcript=[{"run": path.name}], run=path)


PARTS: dict[str, Part] = {
    "abstain": abstain,
    "trust_every_page": trust_every_page,
    "check_page": check_page,
    "draft_finding": draft_finding,
    "decide_enough": decide_enough,
    "investigate": investigate,
    "triage_object": triage_object,
    "write_report": write_report,
    "run_input_loop": run_input_loop,
    "run_end_to_end": run_end_to_end,
}
# The suites that each part can run.
PART_SUITES = {
    "abstain": {"finding", "live investigation", "triage"},
    "trust_every_page": {"injection check"},
    "check_page": {"injection check"},
    "draft_finding": {"finding"},
    "decide_enough": {"enough"},
    "investigate": {"live investigation"},
    "triage_object": {"triage"},
    "write_report": {"report"},
    "run_input_loop": {"input loop"},
    "run_end_to_end": {"end-to-end"},
}


def find_map_object(inputs: Inputs) -> MapObject:
    if isinstance(inputs, PageText | RunState | Conversation):
        raise TypeError("an injection check, report or input loop task has no one map object")
    return inputs if isinstance(inputs, MapObject) else inputs.map_object


def select_graded_sources(task: Task, outcome: Outcome) -> list[Source]:
    """A task from a written state is graded against its own pages only, so the agent cannot add
    or change evidence. A live task is graded against the page the agent stored for its
    finding."""
    if task.suite == "finding":
        assert isinstance(task.inputs, InvestigationState)  # see evals/load.py
        return task.inputs.pages
    return outcome.sources


def grade(task: Task, outcome: Outcome | Decision | bool | str | RunState) -> list[Grade]:
    """The grades that pass or fail; an end-to-end trial's findings are graded against the
    labels apart, in run_task."""
    expected = task.expected
    if isinstance(outcome, RunState) and isinstance(expected, ExpectedRun):
        return [
            grade_property(outcome, expected.property),
            grade_destinations(outcome, expected.destinations),
            grade_journeys(outcome, expected.destinations),
        ]
    if isinstance(outcome, RunState) and isinstance(expected, ExpectedInput):
        return [
            grade_property(outcome, expected.property),
            grade_destinations(outcome, expected.destinations),
        ]
    if isinstance(outcome, str) and isinstance(task.inputs, RunState):
        return [grade_citations(outcome, task.inputs), grade_distances(outcome, task.inputs)]
    if isinstance(outcome, bool) and isinstance(expected, bool):
        return [grade_flagged(outcome, expected)]
    if isinstance(outcome, Decision) and isinstance(expected, ExpectedDecision):
        return [grade_decision(outcome.call, expected)]
    if isinstance(outcome, Outcome) and isinstance(expected, Expected):
        map_object = find_map_object(task.inputs)
        return [
            grade_result(outcome.finding, map_object, expected),
            grade_grounding(outcome.finding, map_object, select_graded_sources(task, outcome)),
        ]
    raise TypeError(f"{task.id}: the part's outcome does not fit the task's expected result")


def dump_outcome(
    task: Task, outcome: Outcome | Decision | bool | str | RunState, saved: dict | None
) -> dict:
    """What a person needs to check the grades; an end-to-end run's state is in its own file,
    saved, which also tells how the query for the addresses ended, next to the branches."""
    if isinstance(outcome, RunState):
        dumped = outcome.model_dump(mode="json", include={"property", "destinations"})
        if isinstance(task.expected, ExpectedRun):
            dumped["branches"] = mark_branches(outcome)
            if saved is not None and saved["addresses"] is not None:
                dumped["branches"] |= {"addresses": saved["addresses"]}
        return dumped
    if isinstance(outcome, bool):
        return {"flagged": outcome}
    if isinstance(outcome, str):
        return {"draft": outcome}
    if isinstance(outcome, Decision):
        return {"call": outcome.call.model_dump(mode="json") if outcome.call else None}
    return {
        "finding": outcome.finding.model_dump(mode="json"),
        # The sources the finding is graded against, so that the grade can be checked later.
        "sources": [s.model_dump(mode="json") for s in select_graded_sources(task, outcome)],
    }


def judge_trial(task: Task, trial: Trial, date: dt.date, saved: dict | None) -> dict | None:
    """What the judges found in a report task's draft or an end-to-end trial's run, with their
    grades and cost; None for a trial of another suite. A report task's grades go with its
    trial, and an end-to-end trial's are saved next to its run, as evals/judge.py saves them.
    The judges run after the part, so that their cost is counted apart, at the judge model's
    price."""
    if isinstance(trial.outcome, str) and isinstance(task.inputs, RunState):
        grades: dict = {"support": [], "interpretation": None, "no_verdict": None}
        with get_usage_metadata_callback() as usage:
            judge.judge_draft(grades, trial.outcome, task.inputs, date, support=False)
        cost = compute_run_cost(usage.usage_metadata, 0)
        return {"judges": sum_up_judges(grades), "judge_grades": grades, "judge_cost_usd": cost}
    if saved is not None and trial.run is not None:
        grades, path = judge.judge_run(saved, trial.run)
        found = sum_up_judges(grades)
        return {"judges": found, "judge_grades": path.name, "judge_cost_usd": grades["cost_usd"]}
    return None


def sum_up_judges(grades: dict) -> dict:
    """What the judges found in one trial: the support grades by kind, if the support judge
    graded any statement, and each other judge's verdict, or error if its answer was cut off or
    does not parse."""
    found: dict = {name: grades[name].get("verdict", "error") for name in JUDGES}
    if grades["support"]:
        found["support"] = Counter(grade.get("grade", "error") for grade in grades["support"])
    return found


def add_up_judges(found: list[dict]) -> dict[str, Counter]:
    """What the judges found over trials or tasks, as counts."""
    total: dict[str, Counter] = {}
    for one in found:
        for name, result in one.items():
            counts = Counter(result) if isinstance(result, dict) else Counter([result])
            total[name] = total.get(name, Counter()) + counts
    return total


def run_task(
    task: Task,
    part: Part,
    k: int,
    record: Callable[[dict], None],
    web_search: WebSearch | None,
    judged: bool = False,
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
        saved = json.loads(trial.run.read_text(encoding="utf-8")) if trial.run else None
        recorded = {
            "task": task.id,
            "trial": n,
            "date": date.isoformat(),
            **dump_outcome(task, trial.outcome, saved),
            "transcript": trial.transcript,
            **counts,
        }
        record(recorded)  # before grading, so that a grader failure does not lose the trial
        grades = grade(task, trial.outcome)
        found = judge_trial(task, trial, date, saved) if judged else None
        if found is not None and task.suite == "report":  # it fails only if a judge says so
            verdicts = found["judges"]
            grades += [Grade(name, verdicts[name] != "fail", (verdicts[name],)) for name in JUDGES]
        graded = {
            "task": task.id,
            "trial": n,
            "passed": all(g.passed for g in grades),
            "grades": [asdict(g) for g in grades],
            **(found or {}),
        }
        if isinstance(task.expected, ExpectedRun) and isinstance(trial.outcome, RunState):
            graded["findings"] = asdict(grade_findings(trial.outcome, task.expected.labels))
        record(graded)
        trials.append(recorded | graded)
    return trials


def summarise(task: Task, trials: list[dict]) -> dict:
    """A live investigation task reports the share of trials with the right result, and an
    end-to-end task its findings against the labels and how each research branch ended. Any
    other task passes or fails each trial: pass@k means at least one of the k trials passed,
    pass^k all of them."""
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
    if task.suite == "live investigation":
        summary["right result share"] = summary["graders"].get("result", 0) / len(trials)
    elif isinstance(task.expected, ExpectedRun):
        summary |= count_label_results(trials)
        summary["branches"] = {
            service: Counter(t["branches"][service] for t in trials if "branches" in t)
            for service in dict.fromkeys(s for t in trials for s in t.get("branches", {}))
        }
    else:
        summary |= {
            "passed": sum(t["passed"] for t in trials),
            "pass@k": any(t["passed"] for t in trials),
            "pass^k": all(t["passed"] for t in trials),
        }
    if judged := [t for t in trials if "judges" in t]:
        summary["judges"] = add_up_judges([t["judges"] for t in judged])
        summary["judge_cost_usd"] = sum(t["judge_cost_usd"] for t in judged)
    return summary


def count_label_results(trials: list[dict]) -> dict:
    """An end-to-end task's label results over its trials, as counts, since five addresses
    give too few labels for a rate to mean much; a trial that stopped has none."""
    graded = [t["findings"] for t in trials if "findings" in t]
    return {
        "labels": Counter(r for found in graded for r in found["results"].values()),
        "false alarms": sum(len(found["false_alarms"]) for found in graded),
    }


def summarise_suites(tasks: list[Task], summaries: dict[str, dict]) -> dict[str, dict]:
    """Each suite on its own, never pooled with another, over its tasks that ran: a fixed
    component suite averages pass@k and pass^k, the live investigation suite the share of right
    results, and the end-to-end suite adds up the label results of its tasks."""
    suites = {}
    for suite in dict.fromkeys(task.suite for task in tasks if task.id in summaries):
        ran = {t.id: summaries[t.id] for t in tasks if t.suite == suite and t.id in summaries}
        summary: dict = {
            "tasks": len(ran),
            "trials": sum(s["trials"] for s in ran.values()),
            "errors": sum(s["errors"] for s in ran.values()),  # trials where the part failed
            "tool_calls": sum(s["tool_calls"] for s in ran.values()),
            "cost_usd": sum(s["cost_usd"] for s in ran.values()),
        }
        if suite == "live investigation":
            summary["right result share"] = statistics.mean(
                s["right result share"] for s in ran.values()
            )
        elif suite == "end-to-end":
            summary["labels"] = sum((s["labels"] for s in ran.values()), Counter())
            summary["false alarms"] = sum(s["false alarms"] for s in ran.values())
        else:
            summary["pass@k"] = statistics.mean(s["pass@k"] for s in ran.values())
            summary["pass^k"] = statistics.mean(s["pass^k"] for s in ran.values())
        if suite == "injection check":  # false alarms and misses apart
            expected = {t.id: t.expected for t in tasks}
            for flagged, name in [(False, "false alarms"), (True, "misses")]:
                summary[name] = sum(
                    s["trials"] - s["errors"] - s["graders"].get("flagged", 0)
                    for id, s in ran.items()
                    if expected[id] is flagged
                )
        if judged := [s for s in ran.values() if "judges" in s]:
            summary["judges"] = add_up_judges([s["judges"] for s in judged])
            summary["judge_cost_usd"] = sum(s["judge_cost_usd"] for s in judged)
        suites[suite] = summary
    return suites


def run(
    tasks: Iterable[Task],
    part: Part,
    k: int,
    out: Path,
    name: str | None = None,
    web_search: WebSearch | None = None,
    judged: bool = False,
) -> dict[str, dict]:
    """Run every task and write each trial to out at once. A cancelled run is incomplete. If
    judged, the judges grade each report of the report and end-to-end suites; the caller checks
    first that they passed calibration.

    An error of the part fails its trial, and the run goes on; an error of a grader or a judge,
    other than a judge's answer that was cut off or does not parse, or a missing or refused web
    search key, stops it. The last line also has each suite's summary.
    """
    if k < 1:
        raise ValueError("k must be at least 1")
    models = [MODEL, INJECTION_MODEL] + ([JUDGE_MODEL] if judged else [])
    if missing := [model for model in models if model not in prices.load().models]:
        raise ValueError(f"no price for {', '.join(missing)}: add it to data/prices.yaml")
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
                **describe_code(),
                "model": MODEL,
                "effort": EFFORT,
                "max_tokens": MAX_TOKENS,
                "injection_model": INJECTION_MODEL,
                "injection_effort": INJECTION_EFFORT,
                "injection_max_tokens": INJECTION_MAX_TOKENS,
            }
            # the judge version, as evals/calibration/passed.yaml records it, and its output tokens
            | (
                {
                    "judge_model": JUDGE_MODEL,
                    "judge_effort": JUDGE_EFFORT,
                    "judge_max_tokens": JUDGE_MAX_TOKENS,
                }
                if judged
                else {}
            )
        )
        try:
            for task in tasks:
                trials = run_task(task, part, k, record, web_search, judged)
                summaries[task.id] = summarise(task, trials)
            complete = True
        finally:
            suites = summarise_suites(tasks, summaries)
            record({"complete": complete, "summaries": summaries, "suites": suites})
    return summaries


def describe_code() -> dict:
    """The commit that the run's code, prompts and tasks are at, and whether any file differs
    from it. Both are None outside a git checkout."""

    def git(*args: str) -> str | None:
        try:
            done = subprocess.run(["git", *args], cwd=EVALS, capture_output=True, text=True)
        except OSError:
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    status = git("status", "--porcelain")
    uncommitted = None if status is None else bool(status)
    return {"commit": git("rev-parse", "HEAD"), "uncommitted": uncommitted}


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

    judged = args.part in JUDGED_PARTS
    try:
        tasks = select_tasks(args.part, args.tasks)
        # only these parts search
        searches = args.part in ("investigate", "run_end_to_end")
        web_search = TavilyWebSearch() if searches else None
        if judged:
            check_calibrated()  # before any paid call
    except (ValueError, WebSearchAccessError) as error:
        parser.error(str(error))
    out = RESULTS / f"{dt.datetime.now(dt.UTC):%Y-%m-%dT%H-%M-%S-%fZ}.jsonl"
    summaries = run(tasks, PARTS[args.part], args.k, out, args.part, web_search, judged)
    for task_id, s in summaries.items():
        graders = ", ".join(f"{name} {n}/{s['trials']}" for name, n in s["graders"].items())
        if "pass@k" in s:
            result = (
                f"{s['passed']}/{s['trials']} passed, pass@k {s['pass@k']}, pass^k {s['pass^k']}"
            )
        elif "labels" in s:
            branches = ", ".join(
                f"{service} {result} {n}"
                for service, results in s["branches"].items()
                for result, n in results.items()
            )
            result = f"{describe_labels(s)}; branches: {branches or 'none'}"
        else:
            result = f"right result in {s['right result share']:.0%} of trials"
        if graders:
            result += f"; graders: {graders}"
        if s["errors"]:
            result += f"; part errors: {s['errors']}"
        result += f"; tool calls: {s['tool_calls']}, cost: ${s['cost_usd']:.4f}"
        if "judges" in s:
            result += f"; judges: {describe_judges(s)}"
        print(f"{task_id}: {result}")
    for suite, s in summarise_suites(tasks, summaries).items():
        if "pass@k" in s:
            result = f"pass@k {s['pass@k']:.2f}, pass^k {s['pass^k']:.2f}"
        elif "labels" in s:
            result = describe_labels(s)
        else:
            result = f"right result share {s['right result share']:.0%}"
        if "misses" in s:
            result += f"; false alarms {s['false alarms']}, misses {s['misses']}"
        if s["errors"]:
            result += f"; part errors: {s['errors']} of {s['trials']} trials"
        cost = f"tool calls: {s['tool_calls']}, cost: ${s['cost_usd']:.4f}"
        if "judges" in s:
            cost += f"; judges: {describe_judges(s)}"
        print(f"Suite {suite}, {s['tasks']} tasks: {result}; {cost}")
    print(f"Trials: {out}")


def describe_labels(summary: dict) -> str:
    """The findings against the labels, for a person: the correct labels among the scored ones,
    those of the objects the trial fetched."""
    labels = summary["labels"]
    scored = labels["correct"] + labels["error"] + labels["miss"]
    return (
        f"correct {labels['correct']} of {scored} scored labels (error {labels['error']}, "
        f"miss {labels['miss']}; not fetched {labels['not fetched']}, "
        f"left out {labels['left out']}), false alarms {summary['false alarms']}"
    )


def describe_judges(summary: dict) -> str:
    """What the judges found, for a person: the statements that the support judge found
    unsupported or contradicted among those it graded so, with the unknown ones and the errors
    apart, each other judge's verdicts, and their cost."""
    judges, parts = summary["judges"], []
    if "support" in judges:
        support = Counter(judges["support"])
        graded = support["supported"] + support["unsupported"] + support["contradicted"]
        parts.append(
            f"support: {support['unsupported'] + support['contradicted']} of {graded} statements "
            f"unsupported or contradicted (unknown {support['unknown']}, error {support['error']})"
        )
    for name in JUDGES:
        verdicts = ", ".join(f"{verdict} {n}" for verdict, n in judges[name].items())
        parts.append(f"{name}: {verdicts}")
    return "; ".join(parts) + f"; cost: ${summary['judge_cost_usd']:.4f}"


if __name__ == "__main__":
    main()
