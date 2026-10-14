"""The command line, on recorded sources with stubbed models and a stubbed web search."""

import sys

import anthropic
import pytest

from out_of_frame import cli, finding, report
from out_of_frame.map_objects import MapError
from tests.test_agent import (
    FREIHEIT_22,
    stub_the_conversation,
    stub_the_models,
    stub_the_sources,
)
from tests.test_finding import ANSWER, FakeModel
from tests.test_investigation import SNIPPET, FakeWebSearch
from tests.test_report import FakeWriter


@pytest.fixture(autouse=True)
def stub_the_keys_and_the_report(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a key that no stub sends anywhere")
    monkeypatch.setattr(cli, "TavilyWebSearch", lambda: FakeWebSearch([SNIPPET]))
    writer = FakeWriter()
    monkeypatch.setattr(report, "build_report_model", lambda: writer)
    stub_the_conversation(monkeypatch)


def run_cli(monkeypatch, message=FREIHEIT_22):
    monkeypatch.setattr(sys, "argv", ["out-of-frame", message])
    cli.main()


def test_the_report_goes_to_stdout_and_the_progress_and_cost_to_stderr(monkeypatch, capsys):
    stub_the_sources(monkeypatch)
    stub_the_models(monkeypatch)
    run_cli(monkeypatch)
    out, err = capsys.readouterr()
    assert out.startswith(f"# What lies around {FREIHEIT_22}\n")
    assert "Fetched the map." in err and "Investigated an object on the web." in err
    assert "fill_references" not in err  # a step the user is not told about
    assert "Tool calls: 5, cost: $0.0400" in err  # a search in each of five investigations


class ReportWriterThatSeesStderr(FakeWriter):
    """Keeps what stderr held when the report was asked for."""

    def __init__(self, capsys):
        super().__init__()
        self.capsys = capsys
        self.stderr_before = ""

    def invoke(self, request):
        self.stderr_before = self.capsys.readouterr().err
        return super().invoke(request)


@pytest.mark.parametrize("service", ["map", "web search"])
def test_a_failed_service_is_told_before_the_report_is_written(monkeypatch, capsys, service):
    if service == "map":
        stub_the_sources(monkeypatch, overpass=[MapError("busy")])
    else:
        stub_the_sources(monkeypatch)
        stub_the_models(monkeypatch)
        monkeypatch.setattr(cli, "TavilyWebSearch", lambda: FakeWebSearch(fails=True))
    writer = ReportWriterThatSeesStderr(capsys)
    monkeypatch.setattr(report, "build_report_model", lambda: writer)
    run_cli(monkeypatch)
    assert cli.FAILURE_NOTICES[service] in writer.stderr_before
    assert capsys.readouterr().out.startswith("# What lies around")


def test_a_model_failure_stops_the_run_and_still_tells_the_cost(monkeypatch, capsys):
    stub_the_sources(monkeypatch)
    stub_the_models(monkeypatch)

    class APIDownError(anthropic.APIError):
        def __init__(self):  # without the HTTP request that the API's own errors carry
            Exception.__init__(self, "the API is down")

    class FailingWriter:
        def invoke(self, request):
            raise APIDownError()

    monkeypatch.setattr(report, "build_report_model", lambda: FailingWriter())
    with pytest.raises(SystemExit) as stopped:
        run_cli(monkeypatch)
    out, err = capsys.readouterr()
    assert stopped.value.code == 1 and out == ""
    assert "Try again later." in err and "Tool calls: 5, cost: $0.0400" in err


def test_the_agent_asks_in_the_terminal_and_goes_on_with_the_answer(monkeypatch, capsys):
    stub_the_sources(
        monkeypatch, {"Freiheit, Berlin": "freiheit-street.json", FREIHEIT_22: "freiheit-22.json"}
    )
    stub_the_models(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda: FREIHEIT_22)
    run_cli(monkeypatch, "Freiheit, Berlin")
    out, err = capsys.readouterr()
    assert err.startswith("Question 1\n> ")
    assert out.startswith(f"# What lies around {FREIHEIT_22}\n")  # stdout holds only the report


def test_an_empty_answer_is_asked_for_again(monkeypatch, capsys):
    stub_the_sources(
        monkeypatch, {"Freiheit, Berlin": "freiheit-street.json", FREIHEIT_22: "freiheit-22.json"}
    )
    stub_the_models(monkeypatch)
    answers = ["", "  ", FREIHEIT_22]
    monkeypatch.setattr("builtins.input", lambda: answers.pop(0))
    run_cli(monkeypatch, "Freiheit, Berlin")
    out, err = capsys.readouterr()
    assert err.startswith("Question 1\n> > > ") and answers == []
    assert out.startswith(f"# What lies around {FREIHEIT_22}\n")


def test_an_empty_message_exits_at_once(monkeypatch, capsys):
    with pytest.raises(SystemExit) as stopped:
        run_cli(monkeypatch, " ")
    assert stopped.value.code == 2 and "give an address or a listing" in capsys.readouterr().err


def test_without_an_answer_the_run_stops(monkeypatch, capsys):
    stub_the_sources(monkeypatch, {"Freiheit, Berlin": "freiheit-street.json"})

    def no_answer():
        raise EOFError

    monkeypatch.setattr("builtins.input", no_answer)
    with pytest.raises(SystemExit) as stopped:
        run_cli(monkeypatch, "Freiheit, Berlin")
    assert stopped.value.code == 2 and "No answer, so the run stops." in capsys.readouterr().err


def test_without_the_model_key_it_exits_at_once(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(SystemExit) as stopped:
        run_cli(monkeypatch)
    assert stopped.value.code == 1 and "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_a_model_answer_outside_its_schema_stops_the_run(monkeypatch, capsys):
    stub_the_sources(monkeypatch)
    stub_the_models(monkeypatch)
    answer = ANSWER | {"identified_type": "a castle"}  # not one of the listed types
    monkeypatch.setattr(finding, "build_finding_model", lambda: FakeModel(answer))
    with pytest.raises(SystemExit) as stopped:
        run_cli(monkeypatch)
    assert stopped.value.code == 1 and "Try again later." in capsys.readouterr().err
