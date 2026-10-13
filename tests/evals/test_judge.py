"""The judge command on recorded sources, with stubbed models and judges: the run is saved
first, then its draft is graded."""

import json
import sys

import pytest
from langchain_core.runnables import RunnableLambda

from evals import judge
from evals.graders import judges
from evals.graders.judges import InterpretationGrade, NoVerdictGrade, SupportGrade
from out_of_frame import geocoding, report
from out_of_frame.config import REPORT_ATTEMPTS
from out_of_frame.geocoding import GeocodingError
from out_of_frame.web_search import MeteredWebSearch, WebSearchAccessError
from tests.evals.test_judges import INTERPRETED, SUPPORTED, answer
from tests.test_agent import FREIHEIT_22, stub_the_models, stub_the_sources
from tests.test_investigation import SNIPPET, FakeWebSearch
from tests.test_report import DATE, FakeWriter

FREE = NoVerdictGrade(reason="No verdict.", free_of_verdicts="yes")
ANSWERS = {SupportGrade: SUPPORTED, InterpretationGrade: INTERPRETED, NoVerdictGrade: FREE}


@pytest.fixture(autouse=True)
def keep_results_in(tmp_path, monkeypatch):
    monkeypatch.setattr(judge, "RESULTS", tmp_path)


def stub_the_judges(monkeypatch, answer_to=lambda schema: answer(ANSWERS[schema])):
    def build(schema):
        return RunnableLambda(lambda messages: answer_to(schema))

    monkeypatch.setattr(judges, "build_judge_model", build)


def run_the_agent(monkeypatch, web_search=None, writer=None) -> dict:
    """A run whose draft, by default, is about one object, so that it is one statement."""
    stub_the_sources(monkeypatch)
    stub_the_models(monkeypatch)
    writer = writer or FakeWriter("An object [osm-way-23156479].")
    monkeypatch.setattr(report, "build_report_model", lambda: writer)
    web_search = MeteredWebSearch(web_search or FakeWebSearch([SNIPPET]))
    return judge.run_agent(FREIHEIT_22, DATE, web_search)


def test_a_run_is_saved_with_its_draft_and_the_investigations_steps(monkeypatch):
    saved = run_the_agent(monkeypatch)
    assert saved["error"] is None and saved["date"] == "2026-10-10"
    assert saved["draft"] == "An object [osm-way-23156479]."
    assert saved["state"]["report"].startswith(f"# What lies around {FREIHEIT_22}")
    steps = [step for step in saved["transcript"] if step["graph"]]
    assert any("write_finding" in step["update"] for step in steps)  # inside the investigation
    assert saved["tool_calls"] == 5 and saved["prices_as_of"]  # a search in each of five
    json.loads(judge.save(saved, "run").read_text(encoding="utf-8"))


def test_a_run_that_stops_is_saved_with_its_error(monkeypatch):
    def fail(text):
        raise GeocodingError("Nominatim is down")

    monkeypatch.setattr(geocoding, "call_nominatim", fail)
    saved = judge.run_agent(FREIHEIT_22, DATE, MeteredWebSearch(FakeWebSearch()))
    assert "Nominatim is down" in saved["error"]
    assert saved["state"]["property"]["text"] == FREIHEIT_22 and saved["state"]["findings"] == []
    assert saved["draft"] is None and saved["cost_usd"] == 0


def test_a_run_that_stops_late_is_saved_with_its_last_state(monkeypatch):
    writer = FakeWriter(*["A site [osm-way-9]."] * REPORT_ATTEMPTS)  # an unknown ID each time
    saved = run_the_agent(monkeypatch, writer=writer)
    assert "ReportError" in saved["error"] and saved["draft"] is None
    findings = saved["state"]["findings"]  # five investigated, six settled by triage
    assert len(findings) == 11 and {found["outcome"] for found in findings} == {"identified"}
    assert saved["tool_calls"] == 5 and len(saved["state"]["sources"]) == 6  # the map, 5 pages


class StoppingWebSearch:
    """A web search that refuses its key, or is cancelled, on the first search."""

    def __init__(self, error: BaseException):
        self.error = error

    def search(self, query):
        raise self.error

    def extract(self, url):
        raise self.error


@pytest.mark.parametrize(
    "error", [WebSearchAccessError("no credits left"), KeyboardInterrupt()], ids=["key", "cancel"]
)
def test_a_run_that_web_search_stops_is_saved_too(monkeypatch, error):
    saved = run_the_agent(monkeypatch, web_search=StoppingWebSearch(error))
    assert type(error).__name__ in saved["error"]
    assert len(saved["state"]["map_objects"]) == 11


def test_the_judges_grade_the_draft_of_a_saved_run(monkeypatch):
    run_file = judge.save(run_the_agent(monkeypatch), "run")
    stub_the_judges(monkeypatch)
    grades, grades_file = judge.judge_run(json.loads(run_file.read_text()), run_file)
    assert json.loads(grades_file.read_text(encoding="utf-8")) == grades
    assert grades["calibrated"] is False and grades["complete"] is True
    assert grades["run"] == run_file.name and len(grades["rubrics_sha256"]) == 3
    assert grades["research_scope_sha256"] and grades["prices_as_of"]
    [support] = grades["support"]
    assert support["statement"] == "An object [osm-way-23156479]."
    assert support["cited"] == ["osm-way-23156479"] and support["grade"] == "supported"
    assert grades["interpretation"]["verdict"] == "pass"
    assert grades["no_verdict"]["verdict"] == "pass"


def test_a_bad_answer_is_saved_as_its_judges_error_and_the_others_go_on(monkeypatch):
    run_file = judge.save(run_the_agent(monkeypatch), "run")

    def answer_to(schema):
        if schema is SupportGrade:
            return answer(SUPPORTED, stop_reason="max_tokens")
        return answer(ANSWERS[schema])

    stub_the_judges(monkeypatch, answer_to)
    grades, _ = judge.judge_run(json.loads(run_file.read_text()), run_file)
    assert "max_tokens" in grades["support"][0]["error"]
    assert grades["interpretation"]["verdict"] == "pass" and grades["complete"] is True


def test_judging_that_stops_is_saved_as_incomplete(monkeypatch, tmp_path):
    run_file = judge.save(run_the_agent(monkeypatch), "run")

    def answer_to(schema):
        if schema is InterpretationGrade:
            raise ConnectionError("the API is down")
        return answer(ANSWERS[schema])

    stub_the_judges(monkeypatch, answer_to)
    with pytest.raises(ConnectionError):
        judge.judge_run(json.loads(run_file.read_text()), run_file)
    [grades_file] = tmp_path.glob("*-grades.json")
    grades = json.loads(grades_file.read_text(encoding="utf-8"))
    assert grades["complete"] is False and grades["support"][0]["grade"] == "supported"


def test_a_saved_run_is_judged_again_without_running_the_agent(monkeypatch, capsys):
    run_file = judge.save(run_the_agent(monkeypatch), "run")
    stub_the_judges(monkeypatch)
    monkeypatch.setattr(judge, "run_agent", lambda *args: pytest.fail("the agent ran again"))
    monkeypatch.setattr(judge, "MODEL", "an agent model without a price")  # not needed here
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a key that no stub sends anywhere")
    monkeypatch.setattr(sys, "argv", ["judge", str(run_file)])
    judge.main()
    out = capsys.readouterr().out
    assert out.startswith("Uncalibrated grades, not to be quoted:\n1. supported: An object")
    assert "interpretation: pass" in out and "no_verdict: pass" in out


def test_a_run_that_stopped_is_not_judged(monkeypatch):
    run_file = judge.save({"error": "Traceback ..."}, "run")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a key that no stub sends anywhere")
    monkeypatch.setattr(sys, "argv", ["judge", str(run_file)])
    with pytest.raises(SystemExit) as stopped:
        judge.main()
    assert stopped.value.code == 1
