"""The runner on hand-written tasks: trials run, are graded and are recorded."""

import datetime as dt
import functools
import json

import pytest

from evals.graders.finding import Expected
from evals.load import Task
from evals.run import Outcome, Trial, abstain, run
from out_of_frame.state import Finding, InvestigationState, NearbyObject, Point, Source

OBJECT = NearbyObject(
    id="obj-1",
    class_="industry",
    name="Test GmbH",
    details={"landuse": "industrial"},
    addresses=[],
    point=Point(lat=52.5, lon=13.4),
    distance_m=100,
    source_id="map-1",
)
EXPECTED = Expected("identified", "production", "operating")
LIVE = Task(id="L", suite="live investigation", date=None, inputs=OBJECT, expected=EXPECTED)
STATE = InvestigationState(object=OBJECT, history=[], pages=[], finding=None)
FIXED = Task(id="F", suite="finding", date=dt.date(2026, 10, 3), inputs=STATE, expected=EXPECTED)


def identify(inputs, date):
    obj = inputs if isinstance(inputs, NearbyObject) else inputs.object
    finding = Finding(
        object_id=obj.id,
        outcome="identified",
        type="production",
        status="operating",
        why_it_matters="",
        key_facts=["Test GmbH"],
        evidence_ids=["map-1"],
    )
    return Trial(Outcome(finding, []), transcript=[], tool_calls=2, cost_usd=0.01)


def test_a_fixed_task_passes_or_fails_each_trial(tmp_path):
    right = run([FIXED], identify, 3, tmp_path / "right.jsonl")["F"]
    wrong = run([FIXED], abstain, 3, tmp_path / "wrong.jsonl")["F"]
    assert right["passed"] == 3 and right["pass@k"] and right["pass^k"]
    assert wrong["passed"] == 0 and not wrong["pass@k"]
    assert right["tool_calls"] == 6


def test_a_live_task_reports_the_share_of_right_results(tmp_path):
    assert run([LIVE], identify, 2, tmp_path / "right.jsonl")["L"]["right result share"] == 1
    assert run([LIVE], abstain, 2, tmp_path / "wrong.jsonl")["L"]["right result share"] == 0


def test_each_trial_starts_from_a_clean_state(tmp_path):
    seen = []

    def change_inputs(inputs, date):
        seen.append(len(inputs.addresses))
        inputs.addresses.append("Teststraße 1")
        return identify(inputs, date)

    run([LIVE], change_inputs, 3, tmp_path / "run.jsonl")
    assert seen == [0, 0, 0]


def test_each_trial_is_recorded_and_the_run_is_marked_complete(tmp_path):
    out = tmp_path / "run.jsonl"
    run([FIXED], identify, 2, out)
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [line.get("trial") for line in lines] == [None, 1, 1, 2, 2, None]
    assert "finding" in lines[1] and "grades" in lines[2]
    assert lines[-1]["complete"] is True


def test_an_earlier_run_is_never_overwritten(tmp_path):
    out = tmp_path / "run.jsonl"
    run([FIXED], identify, 1, out)
    with pytest.raises(FileExistsError):
        run([FIXED], identify, 1, out)


def test_k_below_one_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        run([FIXED], identify, 0, tmp_path / "run.jsonl")


def test_a_fixed_task_ignores_sources_the_agent_adds(tmp_path):
    def invent(inputs, date):
        page = Source(
            id="web-1",
            kind="web search",
            request="x",
            url="https://example.org",
            content="Test GmbH runs a chemical plant.",
        )
        finding = Finding(
            object_id=inputs.object.id,
            outcome="identified",
            type="production",
            status="operating",
            why_it_matters="",
            key_facts=["chemical plant"],
            evidence_ids=["web-1"],
        )
        return Trial(Outcome(finding, [page]), transcript=[], tool_calls=0, cost_usd=0.0)

    summary = run([FIXED], invent, 1, tmp_path / "run.jsonl")["F"]
    assert summary["graders"]["grounding"] == 0


def test_task_ids_must_be_unique(tmp_path):
    with pytest.raises(ValueError, match="more than once"):
        run([FIXED, FIXED], identify, 1, tmp_path / "run.jsonl")


def test_a_trial_is_kept_when_grading_fails(tmp_path, monkeypatch):
    def broken_grade(task, outcome):
        raise RuntimeError("grader bug")

    monkeypatch.setattr("evals.run.grade", broken_grade)
    out = tmp_path / "run.jsonl"
    with pytest.raises(RuntimeError):
        run([FIXED], identify, 1, out)
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert lines[1]["finding"]["type"] == "production"
    assert lines[-1]["complete"] is False


def test_a_part_without_a_name_still_runs(tmp_path):
    assert run([FIXED], functools.partial(identify), 1, tmp_path / "run.jsonl")["F"]["passed"] == 1


def test_a_trial_records_the_sources_it_was_graded_against(tmp_path):
    page = Source(id="web-1", kind="web search", request="x", url="https://example.org", content="")
    task = Task(
        id="F",
        suite="finding",
        date=dt.date(2026, 10, 3),
        inputs=STATE.model_copy(update={"pages": [page]}),
        expected=EXPECTED,
    )
    out = tmp_path / "run.jsonl"
    run([task], identify, 1, out)  # identify returns no sources of its own
    trial = json.loads(out.read_text(encoding="utf-8").splitlines()[1])
    assert [source["id"] for source in trial["sources"]] == ["web-1"]
