"""Run the agent on a first message that completes the input, and grade its report with the
three LLM judges of docs/eval-architecture.md#llm-judges. It stops before any paid call unless
every judge is the version that passed calibration, see evals/calibrate.py.

The run is saved before the judges start, so that a saved run can be judged again without
running the agent. Run with the keys in .env:
uv run --env-file .env python -m evals.judge "Freiheit 22, 13597 Berlin. I travel nowhere."
uv run --env-file .env python -m evals.judge evals/results/<run>.json

The end-to-end suite of evals/run.py saves its runs the same way, so that they can be judged too.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from unittest import mock

from langchain_core.callbacks import get_usage_metadata_callback
from pydantic_core import to_jsonable_python

from evals import dialogue
from evals.calibrate import check_calibrated
from evals.config import JUDGE_EFFORT, JUDGE_MAX_TOKENS, JUDGE_MODEL
from evals.graders import judges
from evals.graders.end_to_end import BranchResult
from evals.graders.judges import (
    RESEARCH_SCOPE,
    RUBRICS,
    JudgeError,
    judge_interpretation,
    judge_no_verdict,
    judge_support,
    split_into_statements,
)
from evals.load import EVALS
from out_of_frame import agent, cli, map_objects, prices
from out_of_frame.config import (
    EFFORT,
    INJECTION_EFFORT,
    INJECTION_MAX_TOKENS,
    INJECTION_MODEL,
    MAX_TOKENS,
    MODEL,
)
from out_of_frame.investigation import Context
from out_of_frame.prices import compute_run_cost
from out_of_frame.record import Record
from out_of_frame.state import RunState
from out_of_frame.web_search import MeteredWebSearch, TavilyWebSearch, WebSearchAccessError

RESULTS = EVALS / "results"


def run_agent(
    message: str, date: dt.date, web_search: MeteredWebSearch
) -> tuple[dict, BaseException | None]:
    """One run of the agent, as it is saved: its model settings, the draft that the judges
    grade, the final state, each step's update, the investigations' steps among them, how the
    query for the addresses of the objects to investigate ended, and the cost. A run that
    stops, even when web search refuses the key or the run is cancelled, is saved too, with its
    error and its last state: it has paid for its calls. The error is also returned, for a
    caller that must stop on it."""
    saved = {
        "message": message,
        "date": date.isoformat(),
        "model": MODEL,
        "effort": EFFORT,
        "max_tokens": MAX_TOKENS,
        "injection_model": INJECTION_MODEL,
        "injection_effort": INJECTION_EFFORT,
        "injection_max_tokens": INJECTION_MAX_TOKENS,
        "draft": None,
        "transcript": [],
        "error": None,
    }
    start, config = agent.start(message), agent.start_thread()
    end: dict | RunState = start
    stopped = None
    addresses: list[BranchResult] = []
    fetch = map_objects.fetch_addresses

    def watch(objects, sources):  # a failure here leaves no trace in the state, by design
        try:
            found = fetch(objects, sources)
        except map_objects.MapError:
            addresses.append("failed")
            raise
        addresses.append("ok" if any(found.values()) else "empty")  # each area, if none found
        return found

    with (
        get_usage_metadata_callback() as usage,
        mock.patch.object(map_objects, "fetch_addresses", watch),
    ):
        try:
            steps = agent.build_graph().stream(
                start,
                config,
                context=Context(date, web_search),
                stream_mode=["updates", "values"],
                subgraphs=True,  # so that a rejected finding and its pages can be read later
            )
            for graph, mode, chunk in steps:
                assert isinstance(chunk, dict)  # an update by node name, or the whole state
                if mode == "values":
                    if not graph:  # the run's state, not an investigation's, without a question
                        end = {key: value for key, value in chunk.items() if key != "__interrupt__"}
                    continue
                saved["transcript"].append({"graph": list(graph), "update": chunk})
                if graph:
                    continue
                for node, update in chunk.items():
                    cli.tell_progress(node, update)
                    if node == "write_report":
                        saved["draft"] = update["report"]
            question = agent.find_question(agent.build_graph(), config)
            if question is not None:  # the judges need a run that the first message completes
                raise dialogue.UnansweredQuestionError(question)
        except (Exception, KeyboardInterrupt) as error:
            saved["error"] = traceback.format_exc()
            stopped = error
    saved["state"] = RunState.model_validate(end)
    saved["addresses"] = addresses[-1] if addresses else None  # None if the query never ran
    saved["tool_calls"] = web_search.tool_calls
    saved["cost_usd"] = compute_run_cost(usage.usage_metadata, web_search.credits)
    saved["prices_as_of"] = prices.load().as_of.isoformat()  # so that stale prices show
    return to_jsonable_python(saved), stopped


def judge_run(saved: dict, run_file: Path) -> tuple[dict, Path]:
    """The three judges' grades of a saved run's draft, and the file they are saved to. A
    judge's answer that was cut off or does not parse is saved as its error, and the other
    judges go on; any other error stops the judging, whose grades are saved as incomplete."""
    state = RunState.model_validate(saved["state"])
    draft, date = saved["draft"], dt.date.fromisoformat(saved["date"])
    folder = Path(judges.__file__).parent
    grades = {
        "calibrated": True,  # its callers judge only after evals.calibrate.check_calibrated
        "run": run_file.name,
        "run_sha256": hashlib.sha256(run_file.read_bytes()).hexdigest(),
        "judge_model": JUDGE_MODEL,
        "judge_effort": JUDGE_EFFORT,
        "judge_max_tokens": JUDGE_MAX_TOKENS,
        "rubrics_sha256": {
            name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
            for name in RUBRICS.values()
        },
        # The judges also get the meanings of the types and statuses from the research scope.
        "research_scope_sha256": hashlib.sha256(RESEARCH_SCOPE.read_bytes()).hexdigest(),
        "prices_as_of": prices.load().as_of.isoformat(),
        "started": dt.datetime.now(dt.UTC).isoformat(),
        "complete": False,
        "support": [],
        "interpretation": None,
        "no_verdict": None,
    }
    with get_usage_metadata_callback() as usage:
        try:
            judge_draft(grades, draft, state, date)
            grades["complete"] = True
        finally:
            grades["cost_usd"] = compute_run_cost(usage.usage_metadata, 0)
            grades = to_jsonable_python(grades)
            path = save(grades, "grades")
            print(f"Grades: {path}, cost: ${grades['cost_usd']:.4f}", file=sys.stderr)
    return grades, path


def judge_draft(
    grades: dict, draft: str, state: RunState, date: dt.date, support: bool = True
) -> None:
    """Fills in the judges' grades of a draft as each judge answers, so that those given are
    kept if judging stops: the support judge's on each statement, unless support is false, then
    the interpretation and no verdict judges'. A judge's answer that was cut off or does not
    parse is saved as its error, and the other judges go on; any other error stops."""
    if support:
        for statement in split_into_statements(draft):
            grade = ask(judge_support, statement, state, date)
            grades["support"].append(
                {"statement": statement.text, "cited": statement.cited} | grade
            )
    grades["interpretation"] = ask(judge_interpretation, draft, state)
    grades["no_verdict"] = ask(judge_no_verdict, draft)


def ask(judge: Callable[..., Record], *args) -> dict:
    """A judge's grade, with its verdict where it has one, or its error."""
    try:
        grade = judge(*args)
    except JudgeError as error:
        return {"error": str(error)}
    verdict = getattr(grade, "verdict", None)
    return grade.model_dump() | ({"verdict": verdict} if verdict else {})


def save(record: dict, name: str) -> Path:
    """The record, written to a new file in evals/results/, which is local only: a run holds
    whole web pages."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{dt.datetime.now(dt.UTC):%Y-%m-%dT%H-%M-%S-%fZ}-{name}.json"
    with path.open("x", encoding="utf-8") as f:  # never overwrite an earlier run
        json.dump(record, f, ensure_ascii=False, indent=2)
    return path


def print_grades(grades: dict) -> None:
    print("Grades of the judge versions that passed calibration:")
    for n, support in enumerate(grades["support"], 1):
        result = support.get("grade") or f"error: {support['error']}"
        print(f"{n}. {result}: {support['statement']}\n   {support.get('reason', '')}")
    for judge in ("interpretation", "no_verdict"):
        grade = grades[judge] or {}
        print(f"{judge}: {grade.get('verdict') or grade.get('error')}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "target",
        help="the user's first message, which must complete the input: a precise address and "
        "where the user travels, if anywhere, with the times; or a saved run's .json file",
    )
    args = parser.parse_args()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        parser.error("set ANTHROPIC_API_KEY, for example in .env: see .env.example")
    run_file = Path(args.target)
    live = run_file.suffix != ".json"
    models = [MODEL, INJECTION_MODEL, JUDGE_MODEL] if live else [JUDGE_MODEL]
    if missing := [model for model in models if model not in prices.load().models]:
        parser.error(f"no price for {', '.join(missing)}: add it to data/prices.yaml")
    try:
        check_calibrated()
    except ValueError as error:
        parser.error(str(error))

    if live:
        try:
            web_search = MeteredWebSearch(TavilyWebSearch())
        except WebSearchAccessError as error:
            parser.exit(1, f"Set TAVILY_API_KEY, for example in .env: {error}\n")
        saved, _ = run_agent(args.target, dt.date.today(), web_search)
        run_file = save(saved, "run")
        cost = f"tool calls: {saved['tool_calls']}, cost: ${saved['cost_usd']:.4f}"
        print(f"Run: {run_file}, {cost}", file=sys.stderr)
    saved = json.loads(run_file.read_text(encoding="utf-8"))
    if saved["error"]:
        parser.exit(1, f"The run stopped, so it has no report to judge: see {run_file}\n")

    grades, _ = judge_run(saved, run_file)
    print_grades(grades)


if __name__ == "__main__":
    main()
