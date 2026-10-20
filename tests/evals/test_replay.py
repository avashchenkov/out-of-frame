"""The report replayed from a saved run, with a stubbed report model and stubbed judges."""

import json
import sys

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from evals import judge, replay
from evals.graders.judges import InterpretationGrade
from out_of_frame import report
from out_of_frame.config import EFFORT, MAX_TOKENS, REPORT_ATTEMPTS
from out_of_frame.state import RunState
from tests.evals.test_judge import ANSWERS, stub_the_judges
from tests.evals.test_judges import answer
from tests.test_report import DATE, STATE, FakeWriter

SAVED = {
    "message": "Please check Freiheit 22, 13597 Berlin.",
    "date": DATE.isoformat(),
    "draft": "The draft the run wrote [osm-way-1].",
    "error": None,
    "state": STATE.model_copy(update={"report": "The report the run wrote."}).model_dump(
        mode="json"
    ),
}


@pytest.fixture(autouse=True)
def keep_results_in(tmp_path, monkeypatch):
    monkeypatch.setattr(judge, "RESULTS", tmp_path)


@pytest.fixture(autouse=True)
def stub_the_models(monkeypatch):
    stub_the_judges(monkeypatch)
    monkeypatch.setattr(report, "build_report_model", lambda: FakeWriter())


def save_run(saved: dict = SAVED):
    return judge.save(saved, "run")


def write_with(monkeypatch, *answers: AIMessage) -> None:
    """The report model answers with these whole answers, with their stop reasons, in turn."""
    left = list(answers)
    writer = RunnableLambda(lambda messages: left.pop(0))
    monkeypatch.setattr(report, "build_report_model", lambda: writer)


def lines(out) -> list[dict]:
    return [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]


def test_a_replay_writes_the_report_again_from_the_saved_state(tmp_path):
    source = save_run()
    replay.replay(replay.load_runs([source]), 2, tmp_path / "replay.jsonl")
    header, written, graded, _, _, last = lines(tmp_path / "replay.jsonl")
    assert header["part"] == "replay_report" and header["effort"] == EFFORT
    assert header["prompts_sha256"].keys() == {
        "report.md.j2",
        "report_task.md.j2",
        "research_scope.yaml",
    }
    assert [written["trial"], graded["trial"]] == [1, 1] and last["complete"] is True
    replayed = json.loads((tmp_path / written["replay"]).read_text(encoding="utf-8"))
    assert replayed["replayed_from"] == source.name and replayed["error"] is None
    assert replayed["effort"] == EFFORT and replayed["max_tokens"] == MAX_TOKENS
    assert replayed["prompts_sha256"] == header["prompts_sha256"]
    assert replayed["draft"] == "An object [osm-way-1]." != SAVED["draft"]
    assert replayed["state"]["findings"] == SAVED["state"]["findings"]


def test_the_report_is_written_for_the_saved_runs_date(monkeypatch, tmp_path):
    writer = FakeWriter()
    monkeypatch.setattr(report, "build_report_model", lambda: writer)
    replay.replay(replay.load_runs([save_run()]), 1, tmp_path / "replay.jsonl")
    assert DATE.isoformat() in writer.requests[0][0].content  # the system prompt


def test_the_replays_state_has_the_replays_report_not_the_saved_runs(tmp_path):
    replay.replay(replay.load_runs([save_run()]), 1, tmp_path / "replay.jsonl")
    written = lines(tmp_path / "replay.jsonl")[1]
    replayed = json.loads((tmp_path / written["replay"]).read_text(encoding="utf-8"))
    state = RunState.model_validate(SAVED["state"])
    assert replayed["state"]["report"] == report.fill_references(replayed["draft"], state)


def test_each_replay_is_graded_by_code_and_by_the_judges(tmp_path):
    source = save_run()
    summary = replay.replay(replay.load_runs([source]), 1, tmp_path / "replay.jsonl")
    written, graded = lines(tmp_path / "replay.jsonl")[1:3]
    assert {g["grader"]: g["passed"] for g in graded["grades"]} == {
        "citations": True,
        "distances": False,  # the stubbed draft gives no distance
    }
    assert graded["judges"] == {
        "interpretation": "pass",
        "no_verdict": "pass",
        "support": {"supported": 1},
    }
    grades = json.loads((tmp_path / graded["judge_grades"]).read_text(encoding="utf-8"))
    assert grades["run"] == written["replay"]
    assert summary[source.name]["graders"] == {"citations": 1, "distances": 0}
    assert summary[source.name]["judges"]["support"] == {"supported": 1}


def test_a_replay_keeps_the_stop_reason_of_each_answer(monkeypatch, tmp_path):
    cut = AIMessage(
        "A draft cut off before it cites", response_metadata={"stop_reason": "max_tokens"}
    )
    whole = AIMessage("An object [osm-way-1].", response_metadata={"stop_reason": "end_turn"})
    write_with(monkeypatch, cut, whole)
    replay.replay(replay.load_runs([save_run()]), 1, tmp_path / "replay.jsonl")
    assert lines(tmp_path / "replay.jsonl")[1]["stop_reasons"] == ["max_tokens", "end_turn"]


def test_a_report_that_fails_fails_its_trial_and_the_replay_goes_on(monkeypatch, tmp_path):
    # each draft cut off at the output tokens before it cites the object
    cut = AIMessage("A draft cut off", response_metadata={"stop_reason": "max_tokens"})
    write_with(monkeypatch, *[cut] * (2 * REPORT_ATTEMPTS))
    summary = replay.replay(replay.load_runs([source := save_run()]), 2, tmp_path / "r.jsonl")
    _, first, second, last = lines(tmp_path / "r.jsonl")
    assert "ReportError" in first["error"] and "ReportError" in second["error"]
    assert first["stop_reasons"] == ["max_tokens"] * REPORT_ATTEMPTS
    assert last["complete"] is True
    assert summary[source.name]["errors"] == 2 and "judges" not in summary[source.name]
    replayed = json.loads((tmp_path / first["replay"]).read_text(encoding="utf-8"))
    assert replayed["draft"] is None and replayed["state"]["report"] is None


def test_a_judge_error_stops_the_replay_and_keeps_the_trials_report(monkeypatch, tmp_path):
    def answer_to(schema):
        if schema is InterpretationGrade:
            raise ConnectionError("the API is down")
        return answer(ANSWERS[schema])

    stub_the_judges(monkeypatch, answer_to)
    with pytest.raises(ConnectionError):
        replay.replay(replay.load_runs([save_run()]), 2, tmp_path / "replay.jsonl")
    _, written, last = lines(tmp_path / "replay.jsonl")
    assert written["trial"] == 1 and written["stop_reasons"] == [None] and "judges" not in written
    assert last == {"complete": False, "summaries": {}}


def test_a_run_that_stopped_or_is_given_twice_is_not_replayed():
    stopped = save_run(SAVED | {"error": "Traceback ..."})
    with pytest.raises(ValueError, match="stopped"):
        replay.load_runs([stopped])
    source = save_run()
    with pytest.raises(ValueError, match="more than once"):
        replay.load_runs([source, source])


def test_a_run_whose_state_the_code_cannot_read_is_not_replayed():
    old = save_run(SAVED | {"state": SAVED["state"] | {"map_objects": "an older shape"}})
    with pytest.raises(ValueError, match="does not fit RunState"):
        replay.load_runs([save_run(), old])


def test_the_command_stops_before_any_paid_call_if_a_judge_did_not_pass(monkeypatch):
    def not_passed():
        raise ValueError("the judge version did not pass calibration")

    monkeypatch.setattr(replay, "check_calibrated", not_passed)
    monkeypatch.setattr(replay, "replay", lambda *args: pytest.fail("the report was replayed"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a key that no stub sends anywhere")
    monkeypatch.setattr(sys, "argv", ["replay", str(save_run())])
    with pytest.raises(SystemExit) as stopped:
        replay.main()
    assert stopped.value.code == 2


def test_the_command_replays_and_prints_each_runs_summary(monkeypatch, capsys):
    monkeypatch.setattr(replay, "check_calibrated", lambda: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a key that no stub sends anywhere")
    monkeypatch.setattr(sys, "argv", ["replay", str(source := save_run()), "--k", "1"])
    replay.main()
    out = capsys.readouterr().out
    assert out.startswith(
        f"{source.name}: report errors 0/1; graders: citations 1/1, distances 0/1"
    )
    assert "interpretation: pass 1" in out and "Trials: " in out
