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
    conversation,
    finding,
    geocoding,
    investigation,
    map_objects,
    plans,
    prompt_injection,
    report,
    transit,
    triage,
)
from out_of_frame.agent import UnansweredQuestionError
from out_of_frame.config import BPLAN_WFS_URL, NOMINATIM_URL, OVERPASS_URL
from out_of_frame.conversation import Change, ExtractedDestination
from out_of_frame.geocoding import GeocodingError
from out_of_frame.map_objects import MapError
from out_of_frame.state import (
    Address,
    Coordinates,
    Destination,
    Finding,
    Journey,
    MapObject,
    Message,
    RunState,
    replace_by_id,
)
from out_of_frame.web_search import PageText, WebSearchError
from tests.test_finding import ANSWER, FakeModel
from tests.test_investigation import SEARCH, SNIPPET, FakeWebSearch
from tests.test_report import GERMAN, FakeWriter, stub_the_translation
from tests.test_triage import UNCLEAR as TRIAGE_UNCLEAR
from tests.test_triage import stub_the_triage

TRIAGE_CLEAR = {
    "clear": True,
    "identified_type": "wastewater plant",
    "status": "operating",
    "key_facts": ["man_made=wastewater_plant"],
}

DATE = dt.date(2026, 10, 10)
NO_PLANS = {
    layer: {"type": "FeatureCollection", "features": []}
    for layer in ["bplan:a_bp_iv", "bplan:b_bp_fs"]
}
FREIHEIT_22 = "Freiheit 22, 13597 Berlin"


def read_fixture(path: str):
    return json.loads((FIXTURES / path).read_text(encoding="utf-8"))


def stub_the_sources(monkeypatch, nominatim=None, overpass=None, wfs=None, transitous=()):
    """Nominatim answers from a recorded response for each address it knows, by default only
    Freiheit 22, and with no match for any other. Overpass answers in turn: by default, the
    map objects around Freiheit 22, then the addresses inside the five industrial ones; an
    answer that is an exception is raised. The B-Plan WFS answers each layer from wfs, by
    default with no plan, or raises wfs if it is an exception. Transitous answers each journey
    in turn with the connections in transitous, or raises an answer that is an exception; by
    default it has no answer, as the user travels nowhere."""
    journeys = list(transitous)

    def call_transitous(start, end, leave):
        answer = journeys.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(transit, "call_transitous", call_transitous)

    def call_wfs(layer, bbox):
        if isinstance(wfs, Exception):
            raise wfs
        return (wfs or NO_PLANS)[layer]

    monkeypatch.setattr(plans, "call_wfs", call_wfs)
    recorded = nominatim or {FREIHEIT_22: "freiheit-22.json"}

    def call_nominatim(text):
        return read_fixture(f"nominatim/{recorded[text]}") if text in recorded else []

    monkeypatch.setattr(geocoding, "call_nominatim", call_nominatim)
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


def stub_the_conversation(
    monkeypatch,
    addresses: dict[str, str | None] | None = None,
    destinations: list[ExtractedDestination] | None = None,
    language: str | None = None,
) -> list:
    """The extract call takes the user's whole last message for the property's address, or
    finds the address that addresses gives for it, None for none, and the user travels to the
    destinations, by default nowhere; the user writes in the language, by default not known;
    the questions are Question 1, Question 2 and so on. Returns what code found missing for
    each question."""
    asked = []

    def extract(state):
        last = state.messages[-1].text
        address = (addresses or {}).get(last, last)
        return Change(property_address=address, destinations=destinations or [])

    def ask(state, missing):
        asked.append(missing)
        return f"Question {len(asked)}"

    monkeypatch.setattr(conversation, "extract", extract)
    monkeypatch.setattr(conversation, "detect_language", lambda state: language)
    monkeypatch.setattr(conversation, "ask", ask)
    return asked


@pytest.fixture(autouse=True)
def stub_the_report_and_the_conversation(monkeypatch):
    """A report that cites every object it is given; a conversation that takes each message
    for an address."""
    writer = FakeWriter()
    monkeypatch.setattr(report, "build_report_model", lambda: writer)
    stub_the_conversation(monkeypatch)


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


def test_a_user_who_writes_german_gets_the_report_in_german(monkeypatch):
    stub_the_sources(monkeypatch)
    stub_the_models(monkeypatch)
    stub_the_conversation(monkeypatch, language="German")
    writer = FakeWriter()
    monkeypatch.setattr(report, "build_report_model", lambda: writer)
    stub_the_translation(monkeypatch, GERMAN)
    state = agent.run([FREIHEIT_22], DATE, FakeWebSearch([SNIPPET]))
    assert state.language == "German"
    assert "Write the whole report in German" in writer.requests[0][0].content
    assert state.report is not None and state.report.startswith(f"# Was liegt um {FREIHEIT_22}")


def test_every_industrial_object_is_investigated_in_parallel(monkeypatch):
    stub_the_sources(monkeypatch)
    stub_the_models(monkeypatch)
    state = agent.run([FREIHEIT_22], DATE, FakeWebSearch([SNIPPET]))
    assert state.property is not None and state.property.coordinates == Coordinates(
        lat=52.5292863, lon=13.2357896
    )
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
        ["nominatim-1", "overpass-1", "bplan-wfs-1", *(f"{id}/web-1" for id in INDUSTRY)]
    )
    assert state.failures == []
    assert state.report is not None
    # Each object links the page of its finding and its own page on the map.
    links = (
        "([example.org](https://example.org), [map](https://www.openstreetmap.org/way/49572120))"
    )
    assert f"An object {links}." in state.report


def test_an_object_that_triage_cannot_settle_is_investigated(monkeypatch):
    addresses = read_fixture("overpass/freiheit-22-addresses.json")
    addresses["elements"].append({"type": "count", "id": 0})  # none inside the Klärwerk
    objects = read_fixture("overpass/freiheit-22.json")
    stub_the_sources(monkeypatch, overpass=[objects, addresses])
    stub_the_models(monkeypatch, TRIAGE_UNCLEAR)
    state = agent.run([FREIHEIT_22], DATE, FakeWebSearch([SNIPPET]))
    railways = {o.id for o in state.map_objects if triage.is_railway(o)}
    assert len(state.findings) == 11 and railways
    for found in state.findings:  # code settles the railways from the map
        web = f"{found.map_object_id}/web-1"
        assert found.evidence_id == ("overpass-1" if found.map_object_id in railways else web)


def test_code_sends_industry_and_anything_proposed_but_a_railway_to_investigation():
    def sent(**tags):
        return agent.is_sent_by_code(build_object(tags), "map")

    assert sent(category="industry", name="A plant", power="plant")  # T3
    assert sent(category="road_rail", highway="proposed", proposed="motorway")
    assert not sent(category="road_rail", railway="construction", construction="rail")
    assert not sent(category="road_rail", railway="rail", ref="6107")
    assert not sent(category="wastewater", man_made="wastewater_plant")
    rail = build_object({"category": "road_rail", "railway": "rail", "ref": "6107"})
    assert agent.is_sent_by_code(rail, "plans")  # the source decides, not the category


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
    state = agent.run([FREIHEIT_22], DATE, FakeWebSearch([SNIPPET, other]))
    assert {source.url for source in state.sources} == {
        NOMINATIM_URL,
        OVERPASS_URL,
        BPLAN_WFS_URL,
        "https://example.org",
    }
    assert state.report is not None and "example.com" not in state.report


def test_a_precise_address_in_the_first_message_starts_research_without_a_question(monkeypatch):
    stub_the_models(monkeypatch)
    stub_the_sources(monkeypatch)
    asked = stub_the_conversation(monkeypatch)
    state = agent.run([FREIHEIT_22], DATE, FakeWebSearch())
    assert asked == [] and state.messages == [Message(role="user", text=FREIHEIT_22)]
    assert state.property == Address(
        text=FREIHEIT_22,
        coordinates=Coordinates(lat=52.5292863, lon=13.2357896),
        source_id="nominatim-1",
    )
    assert state.report is not None


def test_the_agent_asks_until_the_address_resolves_then_goes_on(monkeypatch):
    stub_the_models(monkeypatch)
    stub_the_sources(
        monkeypatch, {"Freiheit, Berlin": "freiheit-street.json", FREIHEIT_22: "freiheit-22.json"}
    )
    asked = stub_the_conversation(monkeypatch, {"Hello": None})
    state = agent.run(["Hello", "Freiheit, Berlin", FREIHEIT_22], DATE, FakeWebSearch())
    # Each question once: on resume the run goes on from the pause, not from the question.
    assert asked == [
        ["The user has not given the property's address."],
        ["'Freiheit, Berlin' matches only a street or an area, not one building."],
    ]
    assert [(message.role, message.text) for message in state.messages] == [
        ("user", "Hello"),
        ("agent", "Question 1"),
        ("user", "Freiheit, Berlin"),
        ("agent", "Question 2"),
        ("user", FREIHEIT_22),
    ]
    assert state.property is not None and state.property.source_id == "nominatim-2"
    assert [source.request for source in state.sources if source.kind == "geocoding"] == [
        "Freiheit, Berlin",
        FREIHEIT_22,
    ]
    assert state.report is not None


def test_a_reply_without_an_address_leaves_the_address_as_it_was(monkeypatch):
    stub_the_models(monkeypatch)
    stub_the_sources(
        monkeypatch, {"Freiheit, Berlin": "freiheit-street.json", FREIHEIT_22: "freiheit-22.json"}
    )
    asked = stub_the_conversation(monkeypatch, {"Which one do you need?": None})
    messages = ["Freiheit, Berlin", "Which one do you need?", FREIHEIT_22]
    state = agent.run(messages, DATE, FakeWebSearch())
    street = ["'Freiheit, Berlin' matches only a street or an area, not one building."]
    assert asked == [street, street]  # the address was geocoded again and is still a street
    assert state.property is not None and state.property.text == FREIHEIT_22


POTSDAM = "Am Kanal 47, 14467 Potsdam"


def test_the_agent_asks_where_the_user_travels_and_when_then_goes_on(monkeypatch):
    stub_the_models(monkeypatch)
    # The journeys are on Wednesday, 14 October: there at 08:00 and back at 16:30, Berlin's
    # summer time. Transitous fails for the way back.
    there = [transit.Connection(dt.datetime(2026, 10, 14, 6, 5, tzinfo=dt.UTC), 50 * 60)]
    stub_the_sources(
        monkeypatch,
        {FREIHEIT_22: "freiheit-22.json", POTSDAM: "am-kanal-47-potsdam.json"},
        transitous=[there, transit.TransitError("busy")],
    )
    asked = stub_the_conversation(monkeypatch)
    work = ExtractedDestination(
        id=None, name="work", address=POTSDAM, leave_home=None, leave_place=None
    )
    times = work.model_copy(
        update={"id": "destination-1", "leave_home": "08:00", "leave_place": "16:30"}
    )
    changes = {
        FREIHEIT_22: Change(property_address=FREIHEIT_22, destinations=None),
        "I work in Potsdam.": Change(property_address=None, destinations=[work]),
        "At 8:00 and 16:30.": Change(property_address=None, destinations=[times]),
    }
    monkeypatch.setattr(conversation, "extract", lambda state: changes[state.messages[-1].text])
    state = agent.run([*changes], DATE, FakeWebSearch())
    assert asked == [
        ["The user has not said where they travel regularly, if anywhere."],
        [
            "The user has not given the clock time when they leave home for 'work'.",
            "The user has not given the clock time when they leave 'work' for home.",
        ],
    ]
    # Each address is geocoded again after each message; the destination may be outside Berlin.
    assert [source.request for source in state.sources if source.kind == "geocoding"] == [
        FREIHEIT_22,
        FREIHEIT_22,
        POTSDAM,
        FREIHEIT_22,
        POTSDAM,
    ]
    potsdam = Address(
        text=POTSDAM,
        coordinates=Coordinates(lat=52.3971923, lon=13.0592866),
        source_id="nominatim-5",
    )
    assert state.destinations == [
        Destination(
            id="destination-1",
            name="work",
            address=potsdam,
            leave_home=dt.time(8),
            leave_place=dt.time(16, 30),
        )
    ]
    assert state.journeys == [
        Journey(
            destination_id="destination-1",
            direction="there",
            outcome="found",
            mean_duration=dt.timedelta(minutes=50),
        ),
        Journey(destination_id="destination-1", direction="back", outcome="unavailable"),
    ]
    assert state.failures == ["transit"] and state.report is not None
    assert (
        "- work: there, leaving home at 08:00 or later, 50 min; back home, leaving it at 16:30 or "
        "later, not known, as the journey planner failed.\n"
    ) in state.report


def test_a_question_after_the_replies_have_run_out_fails_the_run(monkeypatch):
    stub_the_sources(monkeypatch, {"Freiheit, Berlin": "freiheit-street.json"})
    with pytest.raises(UnansweredQuestionError, match="Question 1"):
        agent.run(["Freiheit, Berlin"], DATE, FakeWebSearch())


def test_a_nominatim_failure_stops_the_run(monkeypatch):
    def fail(text):
        raise GeocodingError("Nominatim is down")

    monkeypatch.setattr(geocoding, "call_nominatim", fail)
    with pytest.raises(GeocodingError):
        agent.run([FREIHEIT_22], DATE, FakeWebSearch())


def test_a_map_failure_is_recorded_and_the_run_goes_on(monkeypatch):
    stub_the_sources(monkeypatch, overpass=[MapError("busy")])
    state = agent.run([FREIHEIT_22], DATE, FakeWebSearch())
    assert state.failures == ["map"]
    assert state.map_objects == [] and state.findings == []
    assert state.report is not None  # which says that the map part is missing


PLANS = [  # the five nearest plans around Freiheit 22, nearest first
    "bplan-0508129",
    "bplan-0508286",
    "bplan-0500001VE",
    "bplan-0508000B06",
    "bplan-0508145",
]


def test_every_plan_is_investigated_without_triage_or_addresses(monkeypatch):
    stub_the_sources(monkeypatch, wfs=read_fixture("bplan/freiheit-22.json"))
    stub_the_models(monkeypatch)
    triaged = stub_the_triage(monkeypatch, TRIAGE_CLEAR)
    kinds = {}  # the kind of source that each investigation is given, by object ID
    investigate = investigation.investigate

    def keep_the_kind(map_object, source_kind, date, web_search):
        kinds[map_object.id] = source_kind
        return investigate(map_object, source_kind, date, web_search)

    monkeypatch.setattr(investigation, "investigate", keep_the_kind)
    state = agent.run([FREIHEIT_22], DATE, FakeWebSearch([SNIPPET]))
    assert len(triaged) == 1  # the Klärwerk: code settles the railways, as without plans
    assert {id: kind for id, kind in kinds.items() if kind == "plans"} == dict.fromkeys(
        PLANS, "plans"
    )  # the map objects are given "map"
    found = {finding.map_object_id: finding for finding in state.findings}
    assert all(found[id].evidence_id == f"{id}/web-1" for id in PLANS)  # investigated
    assert all(o.addresses == [] for o in state.map_objects if o.id in PLANS)
    assert state.failures == [] and state.report is not None
    assert "Berlin B-Plan WFS" in state.report  # the plans' own source


def test_a_plans_failure_is_recorded_and_the_run_goes_on(monkeypatch):
    stub_the_sources(monkeypatch, wfs=plans.PlansError("busy"))
    stub_the_models(monkeypatch)
    state = agent.run([FREIHEIT_22], DATE, FakeWebSearch([SNIPPET]))
    assert state.failures == ["plans"]
    assert len(state.map_objects) == 11 and len(state.findings) == 11  # the map part stays
    assert state.report is not None


def test_without_their_addresses_the_objects_are_still_investigated(monkeypatch):
    stub_the_sources(
        monkeypatch, overpass=[read_fixture("overpass/freiheit-22.json"), MapError("busy")]
    )
    stub_the_models(monkeypatch)
    state = agent.run([FREIHEIT_22], DATE, FakeWebSearch([SNIPPET]))
    assert state.failures == []  # the map part of the report stays
    assert all(o.addresses == [] for o in state.map_objects)
    assert len([found for found in state.findings if found.map_object_id in INDUSTRY]) == 5


def test_a_web_search_failure_leaves_the_objects_unidentified(monkeypatch):
    stub_the_sources(monkeypatch)
    stub_the_models(monkeypatch)
    state = agent.run([FREIHEIT_22], DATE, FakeWebSearch(fails=True))
    investigated = [found for found in state.findings if found.map_object_id in INDUSTRY]
    assert sorted(investigated, key=lambda f: f.map_object_id) == [
        Finding.unidentified(id) for id in sorted(INDUSTRY)
    ]
    assert state.failures == ["web search"]
    assert sorted(source.id for source in state.sources) == [
        "bplan-wfs-1",
        "nominatim-1",
        "overpass-1",
    ]


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
    state = agent.run([FREIHEIT_22], DATE, FailingOnce([SNIPPET], fails=True))
    outcomes = sorted(found.outcome for found in state.findings if found.map_object_id in INDUSTRY)
    assert outcomes == ["identified"] * 4 + ["unidentified"]
    assert state.failures == ["web search"] and len(state.sources) == 7  # 3 responses, 4 pages


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
    state = agent.run([FREIHEIT_22], DATE, FakeWebSearch())
    assert len(state.map_objects) == 6 and len(state.findings) == 6
    assert sorted(source.id for source in state.sources) == [
        "bplan-wfs-1",
        "nominatim-1",
        "overpass-1",
    ]
    assert state.report is not None
