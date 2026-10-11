"""One run of the agent on recorded Nominatim and Overpass responses, with stubbed models and a
stubbed web search."""

import datetime as dt
import json

import pytest

from evals.load import FIXTURES
from out_of_frame import (
    agent,
    finding,
    geocoding,
    investigation,
    map_objects,
    prompt_injection,
    report,
)
from out_of_frame.agent import UnclearAddressError
from out_of_frame.geocoding import GeocodingError
from out_of_frame.map_objects import MapError
from out_of_frame.state import Coordinates, Finding
from tests.test_finding import ANSWER, FakeModel
from tests.test_investigation import SEARCH, SNIPPET, FakeSearcher, FakeWebSearch
from tests.test_report import FakeWriter

DATE = dt.date(2026, 10, 10)
FREIHEIT_22 = "Freiheit 22, 13597 Berlin"


def read_fixture(path: str):
    return json.loads((FIXTURES / path).read_text(encoding="utf-8"))


def stub_the_sources(monkeypatch, nominatim="freiheit-22.json", overpass=None):
    """Nominatim answers from a recorded response. Overpass answers in turn: by default, the
    map objects around Freiheit 22, then the addresses inside the chosen one; an answer that
    is an exception is raised."""
    results = read_fixture(f"nominatim/{nominatim}")
    monkeypatch.setattr(geocoding, "call_nominatim", lambda text: results)
    answers = overpass or [
        read_fixture("overpass/freiheit-22.json"),
        read_fixture("overpass/way-23156479-addresses.json"),
    ]

    def call_overpass(query):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(map_objects, "call_overpass", call_overpass)


@pytest.fixture(autouse=True)
def stub_the_report(monkeypatch):
    """A report that cites every object it is given."""
    writer = FakeWriter()
    monkeypatch.setattr(report, "build_report_model", lambda: writer)


def stub_the_models(monkeypatch):
    """One search, then the finding of tests.test_finding; no page is flagged."""
    searcher = FakeSearcher(SEARCH)  # one for the whole run, so that it stops after the search
    monkeypatch.setattr(investigation, "build_search_model", lambda: searcher)
    monkeypatch.setattr(finding, "build_finding_model", lambda: FakeModel(ANSWER))
    monkeypatch.setattr(prompt_injection, "flag_injections", lambda texts: [False] * len(texts))


def test_the_nearest_unnamed_industrial_area_is_investigated(monkeypatch):
    stub_the_sources(monkeypatch)
    stub_the_models(monkeypatch)
    state = agent.run(FREIHEIT_22, DATE, FakeWebSearch([SNIPPET]))
    assert state.property.coordinates == Coordinates(lat=52.5292863, lon=13.2357896)
    [chosen] = state.map_objects
    assert chosen.id == "osm-way-23156479"  # 118 m away; nearer objects have names or are tracks
    assert chosen.addresses == ["Klärwerkstraße 1, 13597 Berlin", "Klärwerkstraße 1A, 13597 Berlin"]
    [found] = state.findings
    assert (found.map_object_id, found.outcome) == ("osm-way-23156479", "identified")
    assert [source.id for source in state.sources] == ["overpass-1", "web-1"]  # web-1 is cited
    assert state.failures == []
    assert state.report is not None
    assert "An object [1, 2]." in state.report and "1. https://example.org" in state.report
    assert "2. OpenStreetMap" in state.report


def test_an_address_without_one_precise_match_stops_the_run(monkeypatch):
    stub_the_sources(monkeypatch, nominatim="freiheit-street.json")
    with pytest.raises(UnclearAddressError):
        agent.run("Freiheit, Berlin", DATE, FakeWebSearch())


def test_a_nominatim_failure_stops_the_run(monkeypatch):
    def fail(text):
        raise GeocodingError("Nominatim is down")

    monkeypatch.setattr(geocoding, "call_nominatim", fail)
    with pytest.raises(GeocodingError):
        agent.run(FREIHEIT_22, DATE, FakeWebSearch())


@pytest.mark.parametrize("failed_query", ["objects", "addresses"])
def test_a_map_failure_is_recorded_and_the_run_goes_on(monkeypatch, failed_query):
    objects = read_fixture("overpass/freiheit-22.json")
    answers = [MapError("busy")] if failed_query == "objects" else [objects, MapError("busy")]
    stub_the_sources(monkeypatch, overpass=answers)
    state = agent.run(FREIHEIT_22, DATE, FakeWebSearch())
    assert state.failures == ["map"]
    assert state.map_objects == [] and state.findings == []
    assert state.report is not None  # which says that the map part is missing


def test_a_web_search_failure_leaves_the_object_unidentified(monkeypatch):
    stub_the_sources(monkeypatch)
    stub_the_models(monkeypatch)
    state = agent.run(FREIHEIT_22, DATE, FakeWebSearch(fails=True))
    assert state.findings == [Finding.unidentified("osm-way-23156479")]
    assert state.failures == ["web search"]
    assert [source.id for source in state.sources] == ["overpass-1"]


def test_with_no_unnamed_industrial_area_nothing_is_investigated(monkeypatch):
    objects = read_fixture("overpass/freiheit-22.json")
    for element in objects["elements"]:
        element.setdefault("tags", {}).setdefault("name", "A named site")
    stub_the_sources(monkeypatch, overpass=[objects])
    state = agent.run(FREIHEIT_22, DATE, FakeWebSearch())
    assert state.map_objects == [] and state.findings == []
    assert [source.id for source in state.sources] == ["overpass-1"]
