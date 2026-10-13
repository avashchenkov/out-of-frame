"""One run of the agent on recorded Nominatim and Overpass responses, with stubbed models and a
stubbed web search."""

import datetime as dt
import json
import threading

import pytest
from langchain_core.messages import AIMessage, ToolMessage

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
from out_of_frame.config import OVERPASS_URL
from out_of_frame.geocoding import GeocodingError
from out_of_frame.map_objects import MapError
from out_of_frame.state import Address, Coordinates, Finding, MapObject, RunState, replace_by_id
from out_of_frame.web_search import PageText, WebSearchError
from tests.test_finding import ANSWER, FakeModel
from tests.test_investigation import SEARCH, SNIPPET, FakeWebSearch
from tests.test_report import FakeWriter
from tests.test_triage import UNCLEAR as TRIAGE_UNCLEAR
from tests.test_triage import stub_the_triage

TRIAGE_CLEAR = {
    "clear": True,
    "identified_type": "railway",
    "status": "operating",
    "key_facts": ["railway=rail"],
}

DATE = dt.date(2026, 10, 10)
FREIHEIT_22 = "Freiheit 22, 13597 Berlin"


def read_fixture(path: str):
    return json.loads((FIXTURES / path).read_text(encoding="utf-8"))


def stub_the_sources(monkeypatch, nominatim="freiheit-22.json", overpass=None):
    """Nominatim answers from a recorded response. Overpass answers in turn: by default, the
    map objects around Freiheit 22, then the addresses inside the five industrial ones; an
    answer that is an exception is raised."""
    results = read_fixture(f"nominatim/{nominatim}")
    monkeypatch.setattr(geocoding, "call_nominatim", lambda text: results)
    answers = overpass or [
        read_fixture("overpass/freiheit-22.json"),
        read_fixture("overpass/freiheit-22-addresses.json"),
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


class SearchOnce:
    """Searches once in each investigation, then answers without a tool call."""

    def invoke(self, request):
        if any(isinstance(message, ToolMessage) for message in request):
            return AIMessage("The sources are enough.")
        name, args = SEARCH
        return AIMessage("", tool_calls=[{"name": name, "args": args, "id": "toolu-1"}])


def stub_the_models(monkeypatch, triage_answer=TRIAGE_CLEAR):
    """Triage settles every object it gets, by default; one search in each investigation, then
    the finding of tests.test_finding, which cites web-1; no page is flagged."""
    stub_the_triage(monkeypatch, triage_answer)
    monkeypatch.setattr(investigation, "build_search_model", SearchOnce)
    monkeypatch.setattr(finding, "build_finding_model", lambda: FakeModel(ANSWER))
    monkeypatch.setattr(prompt_injection, "flag_injections", lambda texts: [False] * len(texts))


INDUSTRY = [  # the five nearest industrial objects around Freiheit 22, nearest first
    "osm-way-49572120",  # Müllverbrennungsanlage Ruhleben, named, with complete tags (T3)
    "osm-way-23156479",  # Klärwerkstraße 1 and 1A
    "osm-way-985575964",  # L1
    "osm-way-813407382",
    "osm-way-185943862",
]


def test_every_industrial_object_is_investigated_in_parallel(monkeypatch):
    stub_the_sources(monkeypatch)
    stub_the_models(monkeypatch)
    state = agent.run(FREIHEIT_22, DATE, FakeWebSearch([SNIPPET]))
    assert state.property.coordinates == Coordinates(lat=52.5292863, lon=13.2357896)
    assert len(state.map_objects) == 11  # each once, though five got their addresses later
    klärwerkstraße = next(o for o in state.map_objects if o.id == "osm-way-23156479")
    assert klärwerkstraße.addresses == [
        "Klärwerkstraße 1, 13597 Berlin",
        "Klärwerkstraße 1A, 13597 Berlin",
    ]
    investigated = [found for found in state.findings if found.map_object_id in INDUSTRY]
    triaged = [found for found in state.findings if found.map_object_id not in INDUSTRY]
    assert len(investigated) == 5 and len(triaged) == 6  # the railways and the Klärwerk
    # Each investigation cites its own web-1, which keeps its object's ID in the run state.
    assert {found.evidence_id for found in investigated} == {f"{id}/web-1" for id in INDUSTRY}
    assert {found.evidence_id for found in triaged} == {"overpass-1"}
    assert sorted(source.id for source in state.sources) == sorted(
        ["overpass-1", *(f"{id}/web-1" for id in INDUSTRY)]
    )
    assert state.failures == []
    assert state.report is not None
    assert "An object [1, 2]." in state.report and "1. https://example.org" in state.report
    assert "2. OpenStreetMap" in state.report and "3." not in state.report


def test_an_object_that_triage_cannot_settle_is_investigated(monkeypatch):
    addresses = read_fixture("overpass/freiheit-22-addresses.json")
    addresses["elements"].append({"type": "count", "id": 0})  # none inside the Klärwerk
    objects = read_fixture("overpass/freiheit-22.json")
    stub_the_sources(monkeypatch, overpass=[objects, addresses])
    stub_the_models(monkeypatch, TRIAGE_UNCLEAR)
    state = agent.run(FREIHEIT_22, DATE, FakeWebSearch([SNIPPET]))
    assert len(state.findings) == 11
    assert all(found.evidence_id == f"{found.map_object_id}/web-1" for found in state.findings)


def test_code_sends_industry_and_anything_proposed_to_investigation():
    def sent(**tags):
        return agent.is_sent_by_code(build_object(tags))

    assert sent(category="industry", name="A plant", power="plant")  # T3
    assert sent(category="road_rail", highway="proposed", proposed="motorway")
    assert sent(category="road_rail", railway="construction", construction="rail")
    assert not sent(category="road_rail", railway="rail", ref="6107")
    assert not sent(category="wastewater", man_made="wastewater_plant")


def build_object(details: dict, id: str = "osm-way-1", distance: float = 100) -> MapObject:
    return MapObject(
        id=id,
        name=details.pop("name", None),
        details=details,
        addresses=[],
        coordinates=Coordinates(lat=52.5, lon=13.2),
        distance_from_property_m=distance,
        source_id="overpass-1",
    )


def test_the_objects_are_investigated_nearest_first_whatever_their_category():
    far = build_object({"category": "industry", "landuse": "industrial"}, "osm-way-1", 1400)
    near = build_object({"category": "road_rail", "highway": "proposed"}, "osm-way-2", 1)
    state = RunState(property=Address(text=FREIHEIT_22), map_objects=[far, near])
    assert agent.choose_objects_to_investigate(state) == [near, far]


def test_an_object_with_the_id_of_one_in_the_state_takes_its_place():
    old = [{"id": "osm-way-1", "addresses": []}, {"id": "osm-way-2"}]  # as yet unvalidated dicts
    new = [{"id": "osm-way-1", "addresses": ["Teststraße 1"]}, {"id": "osm-way-3"}]
    assert replace_by_id(old, new) == [new[0], old[1], new[1]]


def test_only_the_page_the_finding_cites_reaches_the_run_state_and_the_report(monkeypatch):
    stub_the_sources(monkeypatch)
    stub_the_models(monkeypatch)  # the finding cites web-1
    other = PageText("https://example.com/other", "Other GmbH works at Klärwerkstraße 1.")
    state = agent.run(FREIHEIT_22, DATE, FakeWebSearch([SNIPPET, other]))
    assert {source.url for source in state.sources} == {OVERPASS_URL, "https://example.org"}
    assert state.report is not None and "example.com" not in state.report


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


def test_a_map_failure_is_recorded_and_the_run_goes_on(monkeypatch):
    stub_the_sources(monkeypatch, overpass=[MapError("busy")])
    state = agent.run(FREIHEIT_22, DATE, FakeWebSearch())
    assert state.failures == ["map"]
    assert state.map_objects == [] and state.findings == []
    assert state.report is not None  # which says that the map part is missing


def test_without_their_addresses_the_objects_are_still_investigated(monkeypatch):
    stub_the_sources(
        monkeypatch, overpass=[read_fixture("overpass/freiheit-22.json"), MapError("busy")]
    )
    stub_the_models(monkeypatch)
    state = agent.run(FREIHEIT_22, DATE, FakeWebSearch([SNIPPET]))
    assert state.failures == []  # the map part of the report stays
    assert all(o.addresses == [] for o in state.map_objects)
    assert len([found for found in state.findings if found.map_object_id in INDUSTRY]) == 5


def test_a_web_search_failure_leaves_the_objects_unidentified(monkeypatch):
    stub_the_sources(monkeypatch)
    stub_the_models(monkeypatch)
    state = agent.run(FREIHEIT_22, DATE, FakeWebSearch(fails=True))
    investigated = [found for found in state.findings if found.map_object_id in INDUSTRY]
    assert sorted(investigated, key=lambda f: f.map_object_id) == [
        Finding.unidentified(id) for id in sorted(INDUSTRY)
    ]
    assert state.failures == ["web search"]
    assert [source.id for source in state.sources] == ["overpass-1"]


def test_one_failed_investigation_leaves_the_others_their_findings(monkeypatch):
    class FailingOnce(FakeWebSearch):
        """Fails on the first search, of whichever investigation comes first."""

        lock = threading.Lock()

        def search(self, query):
            with self.lock:
                self.fails, failed = False, self.fails
            if failed:
                raise WebSearchError("the service is down")
            return self.snippets

    stub_the_sources(monkeypatch)
    stub_the_models(monkeypatch)
    state = agent.run(FREIHEIT_22, DATE, FailingOnce([SNIPPET], fails=True))
    outcomes = sorted(found.outcome for found in state.findings if found.map_object_id in INDUSTRY)
    assert outcomes == ["identified"] * 4 + ["unidentified"]
    assert state.failures == ["web search"] and len(state.sources) == 5  # the map, 4 pages


def test_with_fewer_than_two_investigations_at_once_the_graph_is_not_built(monkeypatch):
    monkeypatch.setattr(agent, "INVESTIGATIONS_AT_ONCE", 1)
    agent.build_graph.cache_clear()
    try:
        with pytest.raises(ValueError, match="at least 2"):
            agent.build_graph()
    finally:
        agent.build_graph.cache_clear()


def test_with_no_object_to_investigate_the_report_is_still_written(monkeypatch):
    objects = read_fixture("overpass/freiheit-22.json")
    elements = objects["elements"]
    starts = [n for n, element in enumerate(elements) if element["type"] == "count"]
    objects["elements"] = elements[:1] + elements[starts[1] :]  # no industry
    stub_the_sources(monkeypatch, overpass=[objects])  # and no query for addresses
    stub_the_models(monkeypatch)  # triage settles every object
    state = agent.run(FREIHEIT_22, DATE, FakeWebSearch())
    assert len(state.map_objects) == 6 and len(state.findings) == 6
    assert [source.id for source in state.sources] == ["overpass-1"]
    assert state.report is not None
