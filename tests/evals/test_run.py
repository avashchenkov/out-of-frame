"""The runner on hand-written tasks: trials run, are graded and are recorded."""

import datetime as dt
import functools
import json

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from evals.graders.finding import Expected
from evals.load import TASKS, Task
from evals.run import (
    MeteredWebSearch,
    Outcome,
    Trial,
    abstain,
    draft_finding,
    investigate,
    run,
    select_tasks,
)
from out_of_frame import finding, investigation, prices
from out_of_frame.config import MODEL
from out_of_frame.state import Coordinates, Finding, InvestigationState, MapObject, Source
from out_of_frame.web_search import WebSearchAccessError
from tests.test_finding import ANSWER, FakeModel
from tests.test_finding import MAP_OBJECT as ADDRESSED_OBJECT
from tests.test_investigation import SEARCH, SNIPPET, FakeSearcher, FakeWebSearch

MAP_OBJECT = MapObject(
    id="obj-1",
    name="Test GmbH",
    details={"landuse": "industrial"},
    addresses=[],
    coordinates=Coordinates(lat=52.5, lon=13.4),
    distance_from_property_m=100,
    source_id="map-1",
)
EXPECTED = Expected("identified", "production", "operating")
LIVE = Task(id="L", suite="live investigation", date=None, inputs=MAP_OBJECT, expected=EXPECTED)
STATE = InvestigationState(map_object=MAP_OBJECT, history=[], pages=[], finding=None)
FIXED = Task(id="F", suite="finding", date=dt.date(2026, 10, 3), inputs=STATE, expected=EXPECTED)


def identify(inputs, date, web_search):
    map_object = inputs if isinstance(inputs, MapObject) else inputs.map_object
    finding = Finding(
        map_object_id=map_object.id,
        outcome="identified",
        identified_type="production",
        status="operating",
        key_facts=["Test GmbH"],
        evidence_ids=["map-1"],
    )
    return Trial(Outcome(finding, []), transcript=[])


def test_a_fixed_task_passes_or_fails_each_trial(tmp_path):
    right = run([FIXED], identify, 3, tmp_path / "right.jsonl")["F"]
    wrong = run([FIXED], abstain, 3, tmp_path / "wrong.jsonl")["F"]
    assert right["passed"] == 3 and right["pass@k"] and right["pass^k"]
    assert wrong["passed"] == 0 and not wrong["pass@k"]


def test_a_live_task_reports_the_share_of_right_results(tmp_path):
    assert run([LIVE], identify, 2, tmp_path / "right.jsonl")["L"]["right result share"] == 1
    assert run([LIVE], abstain, 2, tmp_path / "wrong.jsonl")["L"]["right result share"] == 0


def test_each_trial_starts_from_a_clean_state(tmp_path):
    seen = []

    def change_inputs(inputs, date, web_search):
        seen.append(len(inputs.addresses))
        inputs.addresses.append("Teststraße 1")
        return identify(inputs, date, web_search)

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
    def invent(inputs, date, web_search):
        page = Source(
            id="web-1",
            kind="web search",
            request="x",
            url="https://example.org",
            content="Test GmbH runs a chemical plant.",
        )
        finding = Finding(
            map_object_id=inputs.map_object.id,
            outcome="identified",
            identified_type="production",
            status="operating",
            key_facts=["chemical plant"],
            evidence_ids=["web-1"],
        )
        return Trial(Outcome(finding, [page]), transcript=[])

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
    assert lines[1]["finding"]["identified_type"] == "production"
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


def test_an_error_of_the_part_fails_its_trial_and_the_run_goes_on(tmp_path):
    calls = []

    def fail_once(inputs, date, web_search):
        calls.append(date)
        if len(calls) == 1:
            raise RuntimeError("model unavailable")
        return identify(inputs, date, web_search)

    out = tmp_path / "run.jsonl"
    summary = run([FIXED], fail_once, 2, out)["F"]
    assert summary["passed"] == 1 and summary["errors"] == 1 and not summary["pass^k"]
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [line.get("trial") for line in lines] == [None, 1, 2, 2, None]
    assert "model unavailable" in lines[1]["error"]
    assert lines[1]["passed"] is False and lines[1]["grades"] == []
    assert "finding" in lines[2] and lines[3]["passed"] is True
    assert lines[-1]["complete"] is True


def test_a_live_task_whose_part_always_fails_has_no_right_results(tmp_path):
    def fail(inputs, date, web_search):
        raise RuntimeError("model unavailable")

    assert run([LIVE], fail, 2, tmp_path / "run.jsonl")["L"]["right result share"] == 0


def test_draft_finding_drafts_the_finding_from_the_state(monkeypatch):
    found = identify(STATE, None, None).outcome.finding
    seen = []

    def fake_draft_finding(state, date):
        seen.append((state, date))
        return found

    monkeypatch.setattr("out_of_frame.finding.draft_finding", fake_draft_finding)
    trial = draft_finding(STATE, dt.date(2026, 10, 3), MeteredWebSearch(None))
    assert seen == [(STATE, dt.date(2026, 10, 3))]
    assert trial.outcome.finding == found
    with pytest.raises(TypeError):
        draft_finding(MAP_OBJECT, dt.date(2026, 10, 3), MeteredWebSearch(None))


def test_a_part_runs_only_the_tasks_of_its_suites():
    assert {task.suite for task in select_tasks("draft_finding", [])} == {"finding"}
    assert {task.suite for task in select_tasks("investigate", [])} == {"live investigation"}
    assert len(select_tasks("abstain", [])) > len(select_tasks("draft_finding", []))
    with pytest.raises(ValueError, match="cannot run L1"):
        select_tasks("draft_finding", [TASKS / "l1.yaml"])


class UsageModel(BaseChatModel):
    """A chat model that answers with a fixed token usage, as the Anthropic API reports it."""

    @property
    def _llm_type(self) -> str:
        return "usage"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        usage = {"input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100}
        answer = AIMessage("", usage_metadata=usage, response_metadata={"model_name": "snapshot"})
        return ChatResult(generations=[ChatGeneration(message=answer)])


def test_the_harness_counts_the_tool_calls_and_the_cost(tmp_path):
    def search_and_read(inputs, date, web_search):
        web_search.search("Teststraße 1 Berlin")
        web_search.extract("https://example.org")
        UsageModel().invoke("a question")
        return identify(inputs, date, web_search)

    summary = run(
        [LIVE], search_and_read, 1, tmp_path / "run.jsonl", web_search=FakeWebSearch([SNIPPET])
    )["L"]
    tavily = prices.load().tavily
    credits = tavily.search_credits + tavily.page_credits
    assert summary["tool_calls"] == 2
    assert summary["cost_usd"] == pytest.approx(prices.load().cost(MODEL, 1000, 100, credits))


def test_a_failed_trial_keeps_what_it_spent(tmp_path):
    def search_then_fail(inputs, date, web_search):
        web_search.search("Teststraße 1 Berlin")
        raise RuntimeError("model unavailable")

    summary = run(
        [LIVE], search_then_fail, 1, tmp_path / "run.jsonl", web_search=FakeWebSearch([SNIPPET])
    )["L"]
    assert summary["errors"] == 1 and summary["tool_calls"] == 1
    tavily = prices.load().tavily
    assert summary["cost_usd"] == pytest.approx(tavily.search_credits * tavily.credit)


def test_a_part_that_searches_in_a_run_without_the_web_fails_its_trial(tmp_path):
    def search(inputs, date, web_search):
        web_search.search("Teststraße 1 Berlin")
        return identify(inputs, date, web_search)

    assert run([LIVE], search, 1, tmp_path / "run.jsonl")["L"]["errors"] == 1


def test_a_refused_web_key_stops_the_run(tmp_path):
    def refused(inputs, date, web_search):
        raise WebSearchAccessError("Tavily refused the key")

    out = tmp_path / "run.jsonl"
    with pytest.raises(WebSearchAccessError):
        run([LIVE, FIXED], refused, 2, out)
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2 and lines[-1]["complete"] is False


def stub_the_model(monkeypatch, searcher, answer):
    monkeypatch.setattr(investigation, "searcher", lambda: searcher)
    monkeypatch.setattr(finding, "finder", lambda: FakeModel(answer))


def test_investigate_keeps_each_step_and_the_cited_pages(monkeypatch):
    stub_the_model(monkeypatch, FakeSearcher(SEARCH), ANSWER)
    other = SNIPPET._replace(url="https://example.com")
    trial = investigate(ADDRESSED_OBJECT, dt.date(2026, 10, 9), FakeWebSearch([SNIPPET, other]))
    assert trial.outcome.finding.outcome == "identified"
    assert [page.id for page in trial.outcome.sources] == ["web-1"]  # web-2 is not cited
    steps = [next(iter(step)) for step in trial.transcript]
    assert steps == [
        "search_or_stop",
        "run_tool",
        "search_or_stop",
        "write_finding",
        "check_grounding",
    ]


def test_investigate_keeps_a_rejected_finding_and_why(monkeypatch):
    stub_the_model(monkeypatch, FakeSearcher(SEARCH), ANSWER | {"key_facts": ["Test GmbH brews"]})
    trial = investigate(ADDRESSED_OBJECT, dt.date(2026, 10, 9), FakeWebSearch([SNIPPET]))
    assert trial.outcome.finding == Finding.unidentified("obj-1")
    drafted = next(step["write_finding"] for step in trial.transcript if "write_finding" in step)
    assert drafted["finding"]["key_facts"] == ["Test GmbH brews"]
    assert "Test GmbH brews" in trial.transcript[-1]["grounding_errors"][0]
    with pytest.raises(TypeError):
        investigate(STATE, dt.date(2026, 10, 9), FakeWebSearch())
