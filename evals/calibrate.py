"""Calibrate the LLM judges against the graded sets in evals/calibration/, see
docs/eval-architecture.md#llm-judges.

form writes a judge's examples as the judge sees them, without their grades, for the graders.
stamp records, once the grades are written, what each example's grades follow: the rubric, the
research scope, and the judge's prompt with its answer schema. check refuses a set whose prompts
have changed since, runs the judge on it three times and compares its answers with the grades,
answer by answer: an answer agrees only if all three trials give it. A judge passes if it
catches every faulty answer and disagrees on at most two of the others; then its model, effort
and set are recorded in evals/calibration/passed.yaml. TODO: evals/run.py runs a judge only
if its version is recorded there.
uv run python -m evals.calibrate form support
uv run python -m evals.calibrate stamp support
uv run --env-file .env python -m evals.calibrate check support
"""

import argparse
import datetime as dt
import hashlib
import json
from dataclasses import dataclass, replace
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Literal

import yaml
from pydantic_core import to_jsonable_python

from evals.graders import judges
from evals.graders.judges import (
    InterpretationGrade,
    JudgeError,
    NoVerdictGrade,
    Statement,
    SupportGrade,
)
from evals.judge import RESEARCH_SCOPE
from evals.load import EVALS
from out_of_frame.config import JUDGE_EFFORT, JUDGE_MODEL
from out_of_frame.record import Record
from out_of_frame.report import CITATION
from out_of_frame.state import RunState

CALIBRATION = EVALS / "calibration"
RESULTS = EVALS / "results"
PASSED = CALIBRATION / "passed.yaml"
RUBRICS = {
    "support": "support.md.j2",
    "interpretation": "interpretation.md.j2",
    "no_verdict": "no_verdict.md.j2",
}
SCHEMAS = {
    "support": SupportGrade,
    "interpretation": InterpretationGrade,
    "no_verdict": NoVerdictGrade,
}
QUESTIONS = ["explains_meaning", "lists_unclear_objects", "tells_failures", "fits_type"]
DISAGREEMENTS_ALLOWED = 2
TRIALS = 3  # an answer agrees only if every trial gives it: a run of the agent asks once

type JudgeName = Literal["support", "interpretation", "no_verdict"]


class Example(Record):
    """One example of a judge's set: a statement or a report's draft from a saved run, which is
    a local file in evals/results/, as it was stored or made faulty on purpose."""

    run: str
    run_sha256: str
    made_faulty: str | None = None  # what was changed on purpose; no grader sees it
    prompt_sha256: str | None = None  # the judge's prompt and answer schema it was graded by


class SupportExample(Example):
    statement: str
    grade: Literal["supported", "unsupported", "contradicted", "unknown"]
    reason: str

    def to_statement(self) -> Statement:
        """The statement with the objects it cites, as judges.split_into_statements finds them."""
        return Statement(self.statement, tuple(dict.fromkeys(CITATION.findall(self.statement))))


class InterpretationExample(Example):
    draft: str
    answers: InterpretationGrade


class NoVerdictExample(Example):
    draft: str
    free_of_verdicts: Literal["yes", "no", "unknown"]
    reason: str


EXAMPLES = {
    "support": SupportExample,
    "interpretation": InterpretationExample,
    "no_verdict": NoVerdictExample,
}


class CalibrationSet(Record):
    graded: dt.date
    # What the grades follow, so that a change to either fails at once, even where the run files
    # are missing; each example's prompt_sha256 also covers the code that writes the prompt.
    rubric_sha256: str
    research_scope_sha256: str  # the types' meanings, which the rubrics quote
    examples: list[SupportExample] | list[InterpretationExample] | list[NoVerdictExample]


@dataclass(frozen=True)
class Answer:
    """One answer of the judge against its grade: for support, whether the statement is
    supported; for interpretation, one question of one report; for no verdict, one report."""

    example: int  # its number in the set, from 1
    question: str
    expected: str
    got: str

    @property
    def faulty(self) -> bool:
        return self.expected in ("no", "not supported")


def load_set(judge: JudgeName, path: Path | None = None) -> CalibrationSet:
    """The judge's set, or the examples in path that are still to be graded."""
    path = path or CALIBRATION / f"{judge}.yaml"
    return parse_set(judge, path.read_text(encoding="utf-8"))


def parse_set(judge: JudgeName, text: str) -> CalibrationSet:
    data = yaml.safe_load(text)
    examples = [EXAMPLES[judge].model_validate(example) for example in data["examples"]]
    return CalibrationSet.model_validate(data | {"examples": examples})


def hash_file(path: Path | Traversable) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_rubric(judge: JudgeName) -> Path:
    return Path(judges.__file__).parent / RUBRICS[judge]


def check_versions(judge: JudgeName, graded: CalibrationSet) -> None:
    """The set was graded by the current rubric and research scope."""
    if hash_file(find_rubric(judge)) != graded.rubric_sha256:
        raise ValueError(f"the {judge} rubric changed after grading: grade the set again")
    if hash_file(RESEARCH_SCOPE) != graded.research_scope_sha256:
        raise ValueError("the research scope changed after grading: grade the set again")


def check_prompts(judge: JudgeName, graded: CalibrationSet) -> None:
    """Each example's prompt is still the one it was graded by."""
    for n, example in enumerate(graded.examples, 1):
        if example.prompt_sha256 != hash_prompt(judge, example):
            raise ValueError(
                f"the {judge} judge's prompt for example {n} is not the one it was graded by: "
                "grade it again, then stamp the set"
            )


def hash_prompt(judge: JudgeName, example: Example) -> str:
    """The prompt and the answer schema that the judge gets for the example."""
    schema = json.dumps(SCHEMAS[judge].model_json_schema(), sort_keys=True)
    return hashlib.sha256((schema + write_prompt(judge, example)).encode()).hexdigest()


def load_run(example: Example) -> tuple[RunState, dt.date]:
    path = RESULTS / example.run
    if hash_file(path) != example.run_sha256:
        raise ValueError(f"{example.run} is not the run file that was graded")
    saved = json.loads(path.read_text(encoding="utf-8"))
    return RunState.model_validate(saved["state"]), dt.date.fromisoformat(saved["date"])


def write_prompt(judge: JudgeName, example: Example) -> str:
    state, date = load_run(example)
    if isinstance(example, SupportExample):
        return judges.write_support_prompt(example.to_statement(), state, date)
    assert isinstance(example, InterpretationExample | NoVerdictExample)
    if judge == "interpretation":
        return judges.write_interpretation_prompt(example.draft, state)
    return judges.write_no_verdict_prompt(example.draft)


def ask_judge(judge: JudgeName, example: Example) -> Record:
    state, date = load_run(example)
    if isinstance(example, SupportExample):
        return judges.judge_support(example.to_statement(), state, date)
    assert isinstance(example, InterpretationExample | NoVerdictExample)
    if judge == "interpretation":
        return judges.judge_interpretation(example.draft, state)
    return judges.judge_no_verdict(example.draft)


def ask_judge_safely(judge: JudgeName, example: Example) -> tuple[Record | None, dict]:
    """The judge's grade, or none if it failed, with what is saved of it."""
    try:
        grade = ask_judge(judge, example)
    except JudgeError as error:
        return None, {"error": str(error)}
    return grade, grade.model_dump()


def compare(n: int, example: Example, grade: Record | None) -> list[Answer]:
    """The judge's answers against the example's grades. A grade of unknown is left out: the
    rubric does not settle it. A judge's error, or its unknown, never agrees."""
    if isinstance(example, SupportExample):
        got = grade.grade if isinstance(grade, SupportGrade) else "error"
        pairs = [("supported", normalise(example.grade), normalise(got))]
    elif isinstance(example, InterpretationExample):
        pairs = [
            (
                question,
                getattr(example.answers, question).answer,
                getattr(grade, question).answer
                if isinstance(grade, InterpretationGrade)
                else "error",
            )
            for question in QUESTIONS
        ]
    else:
        assert isinstance(example, NoVerdictExample)
        got = grade.free_of_verdicts if isinstance(grade, NoVerdictGrade) else "error"
        pairs = [("free_of_verdicts", example.free_of_verdicts, got)]
    return [Answer(n, question, want, got) for question, want, got in pairs if want != "unknown"]


def normalise(grade: str) -> str:
    """Supported or not: the metrics count unsupported and contradicted together."""
    return grade if grade in ("supported", "unknown", "error") else "not supported"


def settle(trials: list[Answer]) -> Answer:
    """The answer that every trial gave; if they differ, one that never agrees, since a run of
    the agent asks the judge once, and that one answer must be one to trust."""
    given = {a.got for a in trials}
    return replace(trials[0], got=given.pop() if len(given) == 1 else "split")


def decide(answers: list[Answer]) -> tuple[bool, list[Answer], list[Answer]]:
    """Whether the judge passes, with the faulty answers it missed and the other answers it
    disagrees on."""
    missed = [a for a in answers if a.faulty and a.got != a.expected]
    disagreed = [a for a in answers if not a.faulty and a.got != a.expected]
    return not missed and len(disagreed) <= DISAGREEMENTS_ALLOWED, missed, disagreed


def write_form(judge: JudgeName, path: Path | None = None) -> Path:
    """The judge's examples, or those in path, as the judge sees them now, without their grades:
    a local file, as the pages in it are."""
    graded = load_set(judge, path)
    parts = [
        f"## Example {n}\n\n{write_prompt(judge, example)}"
        for n, example in enumerate(graded.examples, 1)
    ]
    path = RESULTS / f"calibration-form-{judge}.md"
    path.write_text("\n\n".join(parts), encoding="utf-8")
    return path


def stamp(judge: JudgeName) -> None:
    """Records what the set's grades follow now: only once they are written for the current
    rubric, research scope and prompts. The comments at the top of the file stay."""
    path = CALIBRATION / f"{judge}.yaml"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(True)
    top = next(n for n, line in enumerate(lines) if line.strip() and not line.startswith("#"))
    comments = "".join(lines[:top])
    graded = load_set(judge)
    data = yaml.safe_load(text)
    data["rubric_sha256"] = hash_file(find_rubric(judge))
    data["research_scope_sha256"] = hash_file(RESEARCH_SCOPE)
    for example, stored in zip(graded.examples, data["examples"], strict=True):
        stored["prompt_sha256"] = hash_prompt(judge, example)
    dumped = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)
    path.write_text(comments + dumped, encoding="utf-8")


def check(judge: JudgeName) -> bool:
    """Runs the judge on its set, saves its answers, and records its version if it passes;
    a judge that fails loses any version recorded before. The version is the set as it was
    read, even if the file changes while the judge runs."""
    content = (CALIBRATION / f"{judge}.yaml").read_bytes()
    graded = parse_set(judge, content.decode("utf-8"))
    check_versions(judge, graded)
    check_prompts(judge, graded)
    grades, answers = [], []
    for n, example in enumerate(graded.examples, 1):
        trials = [ask_judge_safely(judge, example) for _ in range(TRIALS)]
        grades.append([saved for _, saved in trials])
        compared = [compare(n, example, grade) for grade, _ in trials]
        answers += [settle(list(same)) for same in zip(*compared, strict=True)]
    passed, missed, disagreed = decide(answers)
    now = f"{dt.datetime.now(dt.UTC):%Y-%m-%dT%H-%M-%S-%fZ}"
    out = RESULTS / f"{now}-calibration-{judge}-grades.json"
    out.write_text(json.dumps(to_jsonable_python(grades), ensure_ascii=False, indent=2))
    record = yaml.safe_load(PASSED.read_text(encoding="utf-8")) if PASSED.exists() else {}
    record = record or {}
    record.pop(judge, None)
    if passed:
        record[judge] = {
            "checked": dt.date.today().isoformat(),
            "judge_model": JUDGE_MODEL,
            "judge_effort": JUDGE_EFFORT,
            # with its prompts' hashes, which evals/run.py checks against the prompts now
            "set_sha256": hashlib.sha256(content).hexdigest(),
            "faulty_answers": sum(a.faulty for a in answers),
            "other_answers": sum(not a.faulty for a in answers),
            "disagreements": len(disagreed),
        }
    PASSED.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    print(f"{judge}: {'passed' if passed else 'failed'}; answers: {out}")
    for kind, wrong in [("missed", missed), ("disagreed", disagreed)]:
        for a in wrong:
            print(f"  {kind}: example {a.example}, {a.question}: {a.got}, expected {a.expected}")
    return passed


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("action", choices=["form", "stamp", "check"])
    parser.add_argument("judge", choices=list(RUBRICS))
    parser.add_argument("--examples", type=Path, help="form: examples still to be graded")
    args = parser.parse_args()
    try:
        if args.action == "form":
            print(f"Form: {write_form(args.judge, args.examples)}")
        elif args.action == "stamp":
            stamp(args.judge)
        elif not check(args.judge):
            parser.exit(1)
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
