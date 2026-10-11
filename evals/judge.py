"""Run the agent on an address and grade its report with the three LLM judges of
docs/eval-architecture.md#llm-judges. The judges are not calibrated until roadmap step 10, so
their grades are printed and saved, never quoted.

The run is saved before the judges start, so that a saved run can be judged again without
running the agent. Run with the keys in .env:
uv run --env-file .env python -m evals.judge "Freiheit 22, 13597 Berlin"
uv run --env-file .env python -m evals.judge evals/results/<run>.json

TODO: in step 10, the end-to-end suite of evals/run.py runs the agent on labelled tasks.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import traceback
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path

from langchain_core.callbacks import get_usage_metadata_callback
from pydantic_core import to_jsonable_python

from evals.graders import judges
from evals.graders.judges import (
    JudgeError,
    judge_interpretation,
    judge_no_verdict,
    judge_support,
    split_into_statements,
)
from evals.load import EVALS
from out_of_frame import agent, cli, prices
from out_of_frame.config import JUDGE_MODEL, MODEL
from out_of_frame.investigation import Context
from out_of_frame.prices import compute_run_cost
from out_of_frame.record import Record
from out_of_frame.state import Address, RunState
from out_of_frame.web_search import MeteredWebSearch, TavilyWebSearch, WebSearchAccessError

RESULTS = EVALS / "results"
RUBRICS = ["support.md.j2", "interpretation.md.j2", "no_verdict.md.j2"]
RESEARCH_SCOPE = files("out_of_frame").joinpath("data/research_scope.yaml")


def run_agent(address: str, date: dt.date, web_search: MeteredWebSearch) -> dict:
    """One run of the agent, as it is saved: the draft that the judges grade, the final state,
    each step's update, the investigations' steps among them, and the cost. A run that stops,
    even when web search refuses the key or the run is cancelled, is saved too, with its error
    and its last state: it has paid for its calls."""
    saved = {"address": address, "date": date.isoformat(), "model": MODEL, "draft": None}
    saved |= {"transcript": [], "error": None}
    start = RunState(property=Address(text=address))
    end: dict | RunState = start
    with get_usage_metadata_callback() as usage:
        try:
            steps = agent.build_graph().stream(
                start,
                context=Context(date, web_search),
                stream_mode=["updates", "values"],
                subgraphs=True,  # so that a rejected finding and its pages can be read later
            )
            for graph, mode, chunk in steps:
                assert isinstance(chunk, dict)  # an update by node name, or the whole state
                if mode == "values":
                    if not graph:  # the run's state, not an investigation's
                        end = chunk
                    continue
                saved["transcript"].append({"graph": list(graph), "update": chunk})
                if graph:
                    continue
                for node, update in chunk.items():
                    if node in cli.PROGRESS:
                        print(cli.PROGRESS[node], file=sys.stderr)
                    if node == "write_report":
                        saved["draft"] = update["report"]
        except Exception, KeyboardInterrupt:
            saved["error"] = traceback.format_exc()
    saved["state"] = RunState.model_validate(end)
    saved["tool_calls"] = web_search.tool_calls
    saved["cost_usd"] = compute_run_cost(usage.usage_metadata, web_search.credits)
    saved["prices_as_of"] = prices.load().as_of.isoformat()  # so that stale prices show
    return to_jsonable_python(saved)


def judge_run(saved: dict, run_file: Path) -> tuple[dict, Path]:
    """The three judges' grades of a saved run's draft, and the file they are saved to. A
    judge's answer that was cut off or does not parse is saved as its error, and the other
    judges go on; any other error stops the judging, whose grades are saved as incomplete."""
    state = RunState.model_validate(saved["state"])
    draft, date = saved["draft"], dt.date.fromisoformat(saved["date"])
    folder = Path(judges.__file__).parent
    grades = {
        "calibrated": False,  # not to be quoted until the judges pass calibration in step 10
        "run": run_file.name,
        "run_sha256": hashlib.sha256(run_file.read_bytes()).hexdigest(),
        "judge_model": JUDGE_MODEL,
        "rubrics_sha256": {
            name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in RUBRICS
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
            for statement in split_into_statements(draft):
                grade = ask(judge_support, statement, state, date)
                grades["support"].append(
                    {"statement": statement.text, "cited": statement.cited} | grade
                )
            grades["interpretation"] = ask(judge_interpretation, draft, state)
            grades["no_verdict"] = ask(judge_no_verdict, draft)
            grades["complete"] = True
        finally:
            grades["cost_usd"] = compute_run_cost(usage.usage_metadata, 0, JUDGE_MODEL)
            grades = to_jsonable_python(grades)
            path = save(grades, "grades")
            print(f"Grades: {path}, cost: ${grades['cost_usd']:.4f}", file=sys.stderr)
    return grades, path


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
    print("Uncalibrated grades, not to be quoted:")
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
    parser.add_argument("target", help="a precise address, or a saved run's .json file")
    args = parser.parse_args()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        parser.error("set ANTHROPIC_API_KEY, for example in .env: see .env.example")
    run_file = Path(args.target)
    live = run_file.suffix != ".json"
    models = [MODEL, JUDGE_MODEL] if live else [JUDGE_MODEL]
    if missing := [model for model in models if model not in prices.load().models]:
        parser.error(f"no price for {', '.join(missing)}: add it to data/prices.yaml")

    if live:
        try:
            web_search = MeteredWebSearch(TavilyWebSearch())
        except WebSearchAccessError as error:
            parser.exit(1, f"Set TAVILY_API_KEY, for example in .env: {error}\n")
        saved = run_agent(args.target, dt.date.today(), web_search)
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
