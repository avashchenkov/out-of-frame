"""The command line, on recorded sources with stubbed models and a stubbed web search."""

import sys

import anthropic
import pytest

from out_of_frame import cli, finding, report
from out_of_frame.map_objects import MapError
from tests.test_agent import FREIHEIT_22, stub_the_models, stub_the_sources
from tests.test_finding import ANSWER, FakeModel
from tests.test_investigation import SNIPPET, FakeWebSearch
from tests.test_report import FakeWriter


@pytest.fixture(autouse=True)
def stub_the_keys_and_the_report(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a key that no stub sends anywhere")
    monkeypatch.setattr(cli, "TavilyWebSearch", lambda: FakeWebSearch([SNIPPET]))
    writer = FakeWriter()
    monkeypatch.setattr(report, "build_report_model", lambda: writer)


def run_cli(monkeypatch, address=FREIHEIT_22):
    monkeypatch.setattr(sys, "argv", ["out-of-frame", address])
    cli.main()


def test_the_report_goes_to_stdout_and_the_progress_and_cost_to_stderr(monkeypatch, capsys):
    stub_the_sources(monkeypatch)
    stub_the_models(monkeypatch)
    run_cli(monkeypatch)
    out, err = capsys.readouterr()
    assert out.startswith(f"# What lies around {FREIHEIT_22}\n")
    assert "Found the address." in err and "Investigated an object on the web." in err
    assert "fill_references" not in err  # a step the user is not told about
    assert "Tool calls: 1, cost: $0.0080" in err  # one search, and the stubbed models cost nothing


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
    assert "Try again later." in err and "Tool calls: 1, cost: $0.0080" in err


def test_an_unclear_address_exits_with_a_hint(monkeypatch, capsys):
    stub_the_sources(monkeypatch, nominatim="freiheit-street.json")
    with pytest.raises(SystemExit) as stopped:
        run_cli(monkeypatch, "Freiheit, Berlin")
    assert stopped.value.code == 2
    assert "give the street, the house number and the postcode" in capsys.readouterr().err


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
