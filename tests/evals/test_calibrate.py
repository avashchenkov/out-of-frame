"""The calibration script on hand-written sets and a stubbed judge: the grades follow the current
rubric, research scope and prompts, and a judge passes only if it catches every faulty
answer."""

import hashlib
import json
from typing import Literal

import pytest
import yaml

from evals import calibrate
from evals.calibrate import (
    QUESTIONS,
    RUBRICS,
    Answer,
    InterpretationExample,
    SupportExample,
    check_versions,
    compare,
    decide,
    load_set,
)
from evals.graders import judges
from evals.graders.judges import Answer as Reply
from evals.graders.judges import InterpretationGrade, NoVerdictGrade, QuestionAnswer, SupportGrade
from out_of_frame.state import RunState


@pytest.mark.parametrize("judge", RUBRICS)
def test_every_set_is_graded_by_its_current_rubric_and_research_scope(judge):
    check_versions(judge, load_set(judge))


RUN = {"run": "run.json", "run_sha256": "0" * 64}


type Grade = Literal["supported", "unsupported", "contradicted", "unknown"]


def support(grade: Grade) -> SupportExample:
    return SupportExample(**RUN, statement="A site [osm-way-1].", grade=grade, reason="")


def test_a_statement_cites_what_its_citations_name():
    statement = "Two sites [osm-way-1], [osm-way-2], and the first again [osm-way-1]."
    example = SupportExample(**RUN, statement=statement, grade="supported", reason="")
    assert example.to_statement().cited == ("osm-way-1", "osm-way-2")


def test_support_counts_unsupported_and_contradicted_together():
    unsupported = SupportGrade(reason="", grade="unsupported")
    [answer] = compare(1, support("contradicted"), unsupported)
    assert answer.faulty and answer.got == answer.expected


def test_an_unknown_or_an_error_of_the_judge_never_agrees():
    [unknown] = compare(1, support("unsupported"), SupportGrade(reason="", grade="unknown"))
    [error] = compare(1, support("supported"), None)
    assert unknown.got != unknown.expected and error.got != error.expected


def test_an_answer_graded_unknown_is_left_out():
    assert compare(1, support("unknown"), SupportGrade(reason="", grade="supported")) == []


def answers(**changed: Reply) -> InterpretationGrade:
    given = {q: QuestionAnswer(reason="", answer=changed.get(q, "yes")) for q in QUESTIONS}
    return InterpretationGrade(**given)


def test_interpretation_is_compared_question_by_question():
    example = InterpretationExample(**RUN, draft="", answers=answers(fits_type="no"))
    compared = compare(1, example, answers(explains_meaning="no"))
    wrong = {a.question for a in compared if a.got != a.expected}
    assert wrong == {"explains_meaning", "fits_type"}
    assert [a.question for a in compared if a.faulty] == ["fits_type"]


def other(got: str) -> Answer:
    return Answer(1, "free_of_verdicts", "yes", got)


def test_a_judge_passes_with_two_other_disagreements_and_no_missed_fault():
    caught = Answer(2, "free_of_verdicts", "no", "no")
    assert decide([caught, other("no"), other("no"), other("yes")])[0]
    assert not decide([caught, other("no"), other("no"), other("no")])[0]
    assert not decide([Answer(2, "free_of_verdicts", "no", "yes"), other("yes")])[0]


def test_an_answer_that_the_trials_split_on_never_agrees():
    trials = [Answer(1, "supported", "supported", got) for got in ("supported",) * 2 + ("no",)]
    assert calibrate.settle(trials).got != "supported"


@pytest.fixture
def no_verdict_set(tmp_path, monkeypatch):
    """A no verdict set of one faulty report and one clean one, in tmp_path, stamped."""
    monkeypatch.setattr(calibrate, "CALIBRATION", tmp_path)
    monkeypatch.setattr(calibrate, "RESULTS", tmp_path)
    monkeypatch.setattr(calibrate, "PASSED", tmp_path / "passed.yaml")
    run = tmp_path / "run.json"
    run.write_text(json.dumps({"date": "2026-10-16", "state": RunState().model_dump(mode="json")}))
    examples = [
        {"run": "run.json", "run_sha256": hashlib.sha256(run.read_bytes()).hexdigest()}
        | {"draft": draft, "free_of_verdicts": verdict, "reason": ""}
        for draft, verdict in [("Buy it.", "no"), ("A railway is 67 m away.", "yes")]
    ]
    graded = {"graded": "2026-10-16", "rubric_sha256": "", "research_scope_sha256": ""}
    text = "# A test set.\n" + yaml.safe_dump(graded | {"examples": examples})
    (tmp_path / "no_verdict.yaml").write_text(text)
    calibrate.stamp("no_verdict")
    return tmp_path


def stub_the_judge(monkeypatch, verdict: Reply):
    grade = NoVerdictGrade(reason="", free_of_verdicts=verdict)
    monkeypatch.setattr(judges, "judge_no_verdict", lambda draft: grade)


def test_an_answer_agrees_only_if_every_trial_gives_it(no_verdict_set, monkeypatch):
    first: list[Reply] = ["no", "no", "no", "yes", "no", "yes"]  # three for each report
    second: list[Reply] = ["no", "yes", "no", "yes", "yes", "yes"]  # for a second check
    replies = iter(first + second)

    def grade(draft):
        return NoVerdictGrade(reason="", free_of_verdicts=next(replies))

    monkeypatch.setattr(judges, "judge_no_verdict", grade)
    assert calibrate.check("no_verdict")  # the fault caught by every trial
    passed = yaml.safe_load((no_verdict_set / "passed.yaml").read_text())
    assert passed["no_verdict"]["disagreements"] == 1  # the clean report, split
    assert not calibrate.check("no_verdict")  # the fault caught by two trials of three


def test_a_judge_that_passes_has_its_version_recorded(no_verdict_set, monkeypatch):
    stub_the_judge(monkeypatch, "no")  # right on the faulty report, wrong on the clean one
    assert calibrate.check("no_verdict")
    passed = yaml.safe_load((no_verdict_set / "passed.yaml").read_text())
    assert passed["no_verdict"]["disagreements"] == 1 and passed["no_verdict"]["judge_model"]
    assert len(list(no_verdict_set.glob("*-calibration-no_verdict-grades.json"))) == 1


def test_the_recorded_version_is_the_set_that_was_judged(no_verdict_set, monkeypatch):
    path = no_verdict_set / "no_verdict.yaml"
    judged = hashlib.sha256(path.read_bytes()).hexdigest()

    def change_the_set_and_answer(draft):  # as if another session stamped a new example
        path.write_text(path.read_text() + "\n# changed\n")
        return NoVerdictGrade(reason="", free_of_verdicts="no")

    monkeypatch.setattr(judges, "judge_no_verdict", change_the_set_and_answer)
    assert calibrate.check("no_verdict")
    passed = yaml.safe_load((no_verdict_set / "passed.yaml").read_text())
    assert passed["no_verdict"]["set_sha256"] == judged


def test_a_judge_that_misses_a_fault_loses_its_recorded_version(no_verdict_set, monkeypatch):
    (no_verdict_set / "passed.yaml").write_text(yaml.safe_dump({"no_verdict": {"old": True}}))
    stub_the_judge(monkeypatch, "yes")
    assert not calibrate.check("no_verdict")
    assert yaml.safe_load((no_verdict_set / "passed.yaml").read_text()) == {}


def test_a_run_file_other_than_the_one_graded_is_refused(no_verdict_set, monkeypatch):
    (no_verdict_set / "run.json").write_text("{}")
    stub_the_judge(monkeypatch, "no")
    with pytest.raises(ValueError, match="not the run file"):
        calibrate.check("no_verdict")


@pytest.mark.parametrize(
    "field, error",
    [("rubric_sha256", "rubric changed"), ("research_scope_sha256", "research scope changed")],
)
def test_a_changed_rubric_or_research_scope_is_refused(no_verdict_set, field, error):
    graded = yaml.safe_load((no_verdict_set / "no_verdict.yaml").read_text())
    (no_verdict_set / "no_verdict.yaml").write_text(yaml.safe_dump(graded | {field: "x"}))
    with pytest.raises(ValueError, match=error):
        calibrate.check("no_verdict")


def test_a_prompt_that_changed_after_grading_is_refused_until_stamped(no_verdict_set, monkeypatch):
    stub_the_judge(monkeypatch, "no")
    monkeypatch.setattr(judges, "write_no_verdict_prompt", lambda draft: f"New words. {draft}")
    with pytest.raises(ValueError, match="example 1 is not the one it was graded by"):
        calibrate.check("no_verdict")
    calibrate.stamp("no_verdict")
    assert calibrate.check("no_verdict")
    assert (no_verdict_set / "no_verdict.yaml").read_text().startswith("# A test set.\n")


def test_the_form_shows_each_example_as_the_judge_sees_it(no_verdict_set):
    form = calibrate.write_form("no_verdict").read_text(encoding="utf-8")
    assert form == "\n\n".join(
        f"## Example {n}\n\n{judges.write_no_verdict_prompt(draft)}"
        for n, draft in [(1, "Buy it."), (2, "A railway is 67 m away.")]
    )
