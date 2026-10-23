"""Replay the report of saved runs: the report written again from each run's final state, at
the model settings of this command, k times. Each replay is saved as a run, as evals/judge.py
saves one, and graded at once by code and by the three LLM judges of
docs/eval-architecture.md#llm-judges. The same inputs at each effort show what the effort
changes in the report alone. A saved run holds the pages it read, so it is not committed as a
task, and its replays stay local in evals/results/ too. It stops before any paid call unless
every judge is the version that passed calibration, see evals/calibrate.py. Run with the keys
in .env:
uv run --env-file .env python -m evals.replay evals/results/<run>-run.json ... --k 3
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import time
import traceback
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from unittest import mock

from langchain_core.callbacks import get_usage_metadata_callback
from pydantic import ValidationError
from pydantic_core import to_jsonable_python

from evals import judge
from evals.calibrate import check_calibrated
from evals.config import JUDGE_EFFORT, JUDGE_MAX_TOKENS, JUDGE_MODEL
from evals.graders.judges import RESEARCH_SCOPE
from evals.graders.report import grade_citations, grade_distances
from evals.run import add_up_judges, describe_code, describe_judges, sum_up_judges
from out_of_frame import prices, report
from out_of_frame.config import EFFORT, MAX_TOKENS, MODEL
from out_of_frame.prices import compute_run_cost
from out_of_frame.state import RunState

PROMPTS = Path(report.__file__).parent / "prompts"
# what the report model reads besides the state: its prompts, and the types of the research scope
REPORT_PROMPTS = [PROMPTS / "report.md.j2", PROMPTS / "report_task.md.j2", RESEARCH_SCOPE]


def hash_prompts() -> dict[str, str]:
    """The versions of what the report model reads besides the state, so that replays before
    and after a change of the prompts or the research scope can be told apart."""
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in REPORT_PROMPTS}


def replay_report(saved: dict, source: Path, trial: int) -> tuple[dict, Path]:
    """One replay of a saved run's report, and the file it is saved to: the saved run's input,
    date, the new draft and the settings and prompts it was written with, with its cost, time
    and the stop reason of each of the model's answers, which shows an answer cut off at the
    output tokens. The state's report is filled in from the new draft, so that a person reads
    the replay's, not the saved run's. A replay whose report fails is saved with its error and
    no report."""
    # the state as the agent had it before its report was written
    state = RunState.model_validate(saved["state"]).model_copy(update={"report": None})
    replayed = {
        "replayed_from": source.name,
        "replayed_from_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "trial": trial,
        "message": saved["message"],
        "date": saved["date"],
        "model": MODEL,
        "effort": EFFORT,
        "max_tokens": MAX_TOKENS,
        "prompts_sha256": hash_prompts(),
        "draft": None,
        "error": None,
        "state": state,
        "stop_reasons": [],
    }
    model = report.build_report_model()

    class Watched:
        """The report model, which keeps the stop reason of each answer."""

        def invoke(self, messages):
            answer = model.invoke(messages)
            replayed["stop_reasons"].append(answer.response_metadata.get("stop_reason"))
            return answer

    watched = Watched()
    start = time.monotonic()
    with (
        get_usage_metadata_callback() as usage,
        mock.patch.object(report, "build_report_model", lambda: watched),
    ):
        try:
            draft = report.write_report(state, dt.date.fromisoformat(saved["date"]))
            replayed["draft"] = draft
            replayed["state"] = state.model_copy(
                update={"report": report.fill_references(draft, state)}
            )
        except Exception:
            replayed["error"] = traceback.format_exc()
    replayed["seconds"] = round(time.monotonic() - start, 1)
    replayed["output_tokens"] = sum(u["output_tokens"] for u in usage.usage_metadata.values())
    replayed["cost_usd"] = compute_run_cost(usage.usage_metadata, 0)
    replayed["prices_as_of"] = prices.load().as_of.isoformat()  # so that stale prices show
    replayed = to_jsonable_python(replayed)
    return replayed, judge.save(replayed, "replay-run")


def replay_trial(saved: dict, source: Path, trial: int, record: Callable[[dict], None]) -> dict:
    """One trial: the report replayed and recorded, then graded by code and by the judges,
    unless it failed, and recorded again. The judges' grades are saved next to the replay, as
    evals/judge.py saves them."""
    replayed, path = replay_report(saved, source, trial)
    recorded = {
        "run": source.name,
        "trial": trial,
        "replay": path.name,
        "error": replayed["error"],
        **{key: replayed[key] for key in ("stop_reasons", "output_tokens", "seconds")},
        "cost_usd": replayed["cost_usd"],
    }
    record(recorded)  # before judging, so that a judge failure does not lose the trial
    if replayed["error"]:
        return recorded | {"grades": []}
    draft, state = replayed["draft"], RunState.model_validate(replayed["state"])
    grades = [grade_citations(draft, state), grade_distances(draft, state)]
    judged, judged_file = judge.judge_run(replayed, path)
    graded = {
        "run": source.name,
        "trial": trial,
        "grades": [asdict(grade) for grade in grades],
        "judges": sum_up_judges(judged),
        "judge_grades": judged_file.name,
        "judge_cost_usd": judged["cost_usd"],
    }
    record(graded)
    return recorded | graded


def summarise(trials: list[dict]) -> dict:
    """A saved run's replays: how many failed, how many each code grader passed, the cost and
    time of the reports, and what the judges found."""
    summary = {
        "trials": len(trials),
        "errors": sum(trial["error"] is not None for trial in trials),
        "graders": {
            name: sum(g["passed"] for t in trials for g in t["grades"] if g["grader"] == name)
            for name in dict.fromkeys(g["grader"] for t in trials for g in t["grades"])
        },
        "cost_usd": sum(trial["cost_usd"] for trial in trials),
        "seconds": sum(trial["seconds"] for trial in trials),
    }
    if judged := [trial for trial in trials if "judges" in trial]:
        summary["judges"] = add_up_judges([trial["judges"] for trial in judged])
        summary["judge_cost_usd"] = sum(trial["judge_cost_usd"] for trial in judged)
    return summary


def load_runs(run_files: list[Path]) -> dict[Path, dict]:
    """The saved runs, each given once, checked before any paid call: a run that stopped has
    no report to replay, and a state saved before the state changed cannot be read."""
    names = [path.name for path in run_files]
    if duplicates := sorted({name for name in names if names.count(name) > 1}):
        raise ValueError(f"runs given more than once: {', '.join(duplicates)}")
    runs = {path: json.loads(path.read_text(encoding="utf-8")) for path in run_files}
    if stopped := [path.name for path, saved in runs.items() if saved["error"]]:
        raise ValueError(f"runs that stopped, with no report to replay: {', '.join(stopped)}")
    for path, saved in runs.items():
        try:
            RunState.model_validate(saved["state"])
        except ValidationError as error:
            raise ValueError(f"{path.name}: the state does not fit RunState: {error}") from error
    return runs


def replay(runs: dict[Path, dict], k: int, out: Path) -> dict[str, dict]:
    """Replay each saved run's report k times and write each trial to out as it is written and
    again as it is graded; the last line has each run's summary. An error of the report fails
    its trial, and the replay goes on; an error of a judge, other than an answer that was cut
    off or does not parse, stops it, with the trial's report recorded. The caller checks first
    that the judges passed calibration."""
    if k < 1:
        raise ValueError("k must be at least 1")
    if missing := [model for model in (MODEL, JUDGE_MODEL) if model not in prices.load().models]:
        raise ValueError(f"no price for {', '.join(missing)}: add it to data/prices.yaml")
    summaries, complete = {}, False
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as f:  # never overwrite an earlier replay

        def record(line: dict) -> None:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
            f.flush()

        record(
            {
                "part": "replay_report",
                "k": k,
                "started": dt.datetime.now(dt.UTC).isoformat(),
                "prices_as_of": prices.load().as_of.isoformat(),
                **describe_code(),
                "model": MODEL,
                "effort": EFFORT,
                "max_tokens": MAX_TOKENS,
                "prompts_sha256": hash_prompts(),
                "judge_model": JUDGE_MODEL,
                "judge_effort": JUDGE_EFFORT,
                "judge_max_tokens": JUDGE_MAX_TOKENS,
            }
        )
        try:
            for path, saved in runs.items():
                trials = [replay_trial(saved, path, n, record) for n in range(1, k + 1)]
                summaries[path.name] = summarise(trials)
            complete = True
        finally:
            record({"complete": complete, "summaries": summaries})
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("runs", nargs="+", type=Path, help="saved runs' .json files")
    parser.add_argument("--k", type=int, default=3, help="replays per run")
    args = parser.parse_args()
    if args.k < 1:
        parser.error("--k must be at least 1")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        parser.error("set ANTHROPIC_API_KEY, for example in .env: see .env.example")
    try:
        runs = load_runs(args.runs)
        check_calibrated()  # before any paid call
    except (OSError, ValueError) as error:
        parser.error(str(error))
    out = judge.RESULTS / f"{dt.datetime.now(dt.UTC):%Y-%m-%dT%H-%M-%S-%fZ}-replay.jsonl"
    summaries = replay(runs, args.k, out)
    for name, s in summaries.items():
        graders = ", ".join(f"{grader} {n}/{s['trials']}" for grader, n in s["graders"].items())
        result = f"report errors {s['errors']}/{s['trials']}; graders: {graders or 'none'}"
        result += f"; cost: ${s['cost_usd']:.4f}, time: {s['seconds']:.0f} s"
        if "judges" in s:
            result += f"; judges: {describe_judges(s)}"
        print(f"{name}: {result}")
    print(f"Trials: {out}")


if __name__ == "__main__":
    main()
