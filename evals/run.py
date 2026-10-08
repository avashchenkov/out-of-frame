"""Run eval tasks: k trials per task, each graded as soon as it is recorded.

See docs/eval-architecture.md#running-the-evals. Run: uv run python -m evals.run --part abstain
"""

import argparse
import datetime as dt
import json
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from evals.graders.finding import Grade, grade_grounding, grade_result
from evals.load import EVALS, Inputs, Task, load, load_all
from out_of_frame.state import Finding, InvestigationState, MapObject, Source

RESULTS = EVALS / "results"


@dataclass(frozen=True)
class Outcome:
    """The state where the suite ends."""

    finding: Finding
    sources: list[Source]  # the snippets and pages the agent stored for the finding


@dataclass(frozen=True)
class Trial:
    """What a part returns.

    TODO: in step 5, the harness gives the part model and Tavily clients that count the tool
    calls and the cost and record the sources, instead of trusting the part's own report.
    """

    outcome: Outcome
    transcript: list[dict]  # for a person who looks into a failure; no grader reads it
    tool_calls: int
    cost_usd: float


# The part of the agent a suite runs. It gets only the task's inputs and the date.
type Part = Callable[[Inputs, dt.date], Trial]


def abstain(inputs: Inputs, date: dt.date) -> Trial:
    """A stub that never identifies anything."""
    map_object = inputs if isinstance(inputs, MapObject) else inputs.map_object
    finding = Finding(
        map_object_id=map_object.id,
        outcome="unidentified",
        identified_type=None,
        status=None,
        why_it_matters="",
        key_facts=[],
        evidence_ids=[],
    )
    return Trial(Outcome(finding, []), transcript=[], tool_calls=0, cost_usd=0.0)


PARTS: dict[str, Part] = {"abstain": abstain}


def graded_sources(task: Task, outcome: Outcome) -> list[Source]:
    """A task from a written state is graded against its own pages only, so the agent cannot add
    or change evidence. A live task is graded against the sources the agent stored."""
    if isinstance(task.inputs, InvestigationState):
        return task.inputs.pages
    return outcome.sources


def grade(task: Task, outcome: Outcome) -> list[Grade]:
    inputs = task.inputs
    map_object = inputs if isinstance(inputs, MapObject) else inputs.map_object
    return [
        grade_result(outcome.finding, map_object, task.expected),
        grade_grounding(outcome.finding, map_object, graded_sources(task, outcome)),
    ]


def run_task(task: Task, part: Part, k: int, record: Callable[[dict], None]) -> list[dict]:
    trials = []
    for n in range(1, k + 1):
        date = task.date or dt.date.today()
        trial = part(task.inputs.model_copy(deep=True), date)  # each trial from a clean state
        recorded = {
            "task": task.id,
            "trial": n,
            "date": date.isoformat(),
            "finding": trial.outcome.finding.model_dump(mode="json"),
            # The sources the finding is graded against, so that the grade can be checked later.
            "sources": [s.model_dump(mode="json") for s in graded_sources(task, trial.outcome)],
            "transcript": trial.transcript,
            "tool_calls": trial.tool_calls,
            "cost_usd": trial.cost_usd,
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
        "tool_calls": sum(t["tool_calls"] for t in trials),
        "cost_usd": sum(t["cost_usd"] for t in trials),
    }
    if suite == "live investigation":
        summary["right result share"] = summary["graders"]["result"] / len(trials)
    else:
        summary |= {
            "passed": sum(t["passed"] for t in trials),
            "pass@k": any(t["passed"] for t in trials),
            "pass^k": all(t["passed"] for t in trials),
        }
    return summary


def run(
    tasks: Iterable[Task], part: Part, k: int, out: Path, name: str | None = None
) -> dict[str, dict]:
    """Run every task and write each trial to out at once. A cancelled run is incomplete.

    TODO: in step 5, record an error of the part as a failed trial instead of stopping the run;
    an error of a grader still stops it. Average pass@k and pass^k over each suite.
    """
    if k < 1:
        raise ValueError("k must be at least 1")
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

        # TODO: record the commit and a hash of each task and state, with the first real runs in
        # step 5, so that a result can be reproduced after the tasks change.
        record(
            {
                "part": name or getattr(part, "__name__", repr(part)),
                "k": k,
                "started": dt.datetime.now(dt.UTC).isoformat(),
            }
        )
        try:
            for task in tasks:
                summaries[task.id] = summarise(task.suite, run_task(task, part, k, record))
            complete = True
        finally:
            record({"complete": complete, "summaries": summaries})
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tasks", nargs="*", type=Path, help="task files; all tasks if none")
    parser.add_argument("--part", choices=PARTS, required=True)
    parser.add_argument("--k", type=int, default=3, help="trials per task")
    args = parser.parse_args()
    if args.k < 1:
        parser.error("--k must be at least 1")

    tasks = [load(path) for path in args.tasks] or load_all()
    out = RESULTS / f"{dt.datetime.now(dt.UTC):%Y-%m-%dT%H-%M-%S-%fZ}.jsonl"
    for task_id, s in run(tasks, PARTS[args.part], args.k, out, args.part).items():
        graders = ", ".join(f"{name} {n}/{s['trials']}" for name, n in s["graders"].items())
        if "pass@k" in s:
            result = (
                f"{s['passed']}/{s['trials']} passed, pass@k {s['pass@k']}, pass^k {s['pass^k']}"
            )
        else:
            result = f"right result in {s['right result share']:.0%} of trials"
        print(f"{task_id}: {result}; graders: {graders}")
    print(f"Trials: {out}")


if __name__ == "__main__":
    main()
