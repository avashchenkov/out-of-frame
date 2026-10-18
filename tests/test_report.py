"""The report with a stubbed model: what the model gets, and how code fills in the references."""

import datetime as dt
import re

import pytest
from langchain_core.messages import AIMessage

from out_of_frame import report
from out_of_frame.config import REPORT_ATTEMPTS
from out_of_frame.report import ReportError, fill_references, write_report
from out_of_frame.state import (
    Address,
    Coordinates,
    Destination,
    Finding,
    Journey,
    MapObject,
    RunState,
    Source,
)

DATE = dt.date(2026, 10, 10)
SITE = MapObject(
    id="osm-way-1",
    name=None,
    details={"landuse": "industrial", "category": "industry"},
    addresses=["Teststraße 1, 13597 Berlin"],
    coordinates=Coordinates(lat=52.5, lon=13.4),
    distance_from_property_m=118,
    source_id="overpass-1",
)
MAP = Source(id="overpass-1", kind="map", request="[out:json];", url="https://overpass", content="")
PAGE = Source(
    id="web-1",
    kind="web search",
    request="Teststraße 1 Berlin",
    url="https://example.org/test-gmbh",
    content="Test GmbH makes parts at Teststraße 1.",
)
FOUND = Finding(
    map_object_id="osm-way-1",
    outcome="identified",
    identified_type="production",
    status=None,
    key_facts=["Test GmbH makes parts"],
    evidence_id="web-1",
)
STATE = RunState(
    property=Address(text="Freiheit 22, 13597 Berlin"),
    sources=[MAP, PAGE],
    map_objects=[SITE],
    findings=[FOUND],
)


class FakeWriter:
    """Answers with the given drafts in turn, or, by default, cites every object it is given;
    keeps every request."""

    def __init__(self, *drafts: str):
        self.drafts = list(drafts)
        self.requests = []

    def invoke(self, request):
        self.requests.append(request)
        if self.drafts:
            return AIMessage(self.drafts.pop(0))
        ids = re.findall(r"^\[(\S+)\] An object", request[-1].content, re.MULTILINE)
        return AIMessage(" ".join(f"An object [{id}]." for id in ids) or "No object is listed.")


def write(monkeypatch, state=STATE, *drafts):
    """The report a person reads, from the draft the model writes."""
    writer = FakeWriter(*drafts)
    monkeypatch.setattr(report, "build_report_model", lambda: writer)
    return fill_references(write_report(state, DATE), state), writer


def with_a_plan() -> RunState:
    """STATE with a development plan, obj-2, and a map object, obj-3, that have the same data:
    only their sources tell them apart."""
    plans = Source(id="bplan-wfs-1", kind="plans", request="", url="", content="")
    fields = {"planname": "VIII-B6", "bp_rechtsstand": "In Kraft getreten", "category": "industry"}
    plan = SITE.model_copy(update={"id": "obj-2", "details": fields, "source_id": plans.id})
    site = SITE.model_copy(update={"id": "obj-3", "details": fields})
    return STATE.model_copy(
        update={"sources": [*STATE.sources, plans], "map_objects": [plan, site], "findings": []}
    )


def test_a_plan_is_marked_by_its_source_alone(monkeypatch):
    _, writer = write(monkeypatch, with_a_plan())
    system, task = writer.requests[0]
    assert "[obj-2] An object 118 m from the property, a development plan. Its map" in task.content
    assert "[obj-3] An object 118 m from the property. Its map" in task.content
    assert "unknown whether building has started" in system.content
    rules = " ".join(system.content.split())
    assert "for a plan still in the planning procedure, what it is meant to allow" in rules
    assert "never that its type shows no effect or that it is harmless" in rules
    assert "the land at that distance has a development plan" in rules


def test_the_model_gets_whole_metres_and_reads_0_m_by_its_rules(monkeypatch):
    near = SITE.model_copy(update={"distance_from_property_m": 0.4})
    far = SITE.model_copy(update={"id": "osm-way-2", "distance_from_property_m": 117.6})
    _, writer = write(monkeypatch, STATE.model_copy(update={"map_objects": [near, far]}))
    [[system, task]] = writer.requests
    assert "[osm-way-1] An object 0 m from the property. Its map" in task.content
    assert "[osm-way-2] An object 118 m from the property. Its map" in task.content
    rule = "A distance of 0 m means that the property lies in the object's area or right next to it"
    assert rule in " ".join(system.content.split())


def test_code_says_what_a_development_plan_is(monkeypatch):
    text, _ = write(monkeypatch)
    assert "A development plan, or Bebauungsplan, sets the legal rules" in text


def test_the_model_writes_a_draft_that_cites_object_ids(monkeypatch):
    monkeypatch.setattr(report, "build_report_model", lambda: FakeWriter("A site [osm-way-1]."))
    assert write_report(STATE, DATE) == "A site [osm-way-1]."


def test_a_citation_becomes_the_numbers_of_its_sources(monkeypatch):
    text, _ = write(monkeypatch, STATE, "A workshop 118 m away makes parts [osm-way-1].")
    assert text.startswith("# What lies around Freiheit 22, 13597 Berlin\n")
    assert "makes parts [1, 2]." in text
    assert "Sources:\n1. https://example.org/test-gmbh\n2. OpenStreetMap\n" in text
    assert text.endswith(report.OSM_CREDIT)


def test_a_finding_that_cites_the_map_names_it_once(monkeypatch):
    from_the_map = FOUND.model_copy(update={"evidence_id": "overpass-1"})
    state = STATE.model_copy(update={"findings": [from_the_map]})
    text, _ = write(monkeypatch, state, "A workshop [osm-way-1].")
    assert "A workshop [1]." in text and "Sources:\n1. OpenStreetMap\n" in text


def test_an_unidentified_object_cites_its_map_data(monkeypatch):
    state = STATE.model_copy(update={"findings": [Finding.unidentified("osm-way-1")]})
    text, _ = write(monkeypatch, state, "An unidentified industrial area [osm-way-1].")
    assert "industrial area [1]." in text and "Sources:\n1. OpenStreetMap\n" in text


def test_the_model_gets_the_map_data_without_the_category_and_the_failures(monkeypatch):
    state = STATE.model_copy(update={"failures": ["web search"]})
    _, writer = write(monkeypatch, state)
    [[system, task]] = writer.requests
    assert "2026-10-10" in system.content and "- production:" in system.content
    assert "[osm-way-1] An object 118 m from the property" in task.content
    assert "landuse=industrial" in task.content and "category" not in task.content
    assert "Finding: production, status not given. Key facts: Test GmbH makes parts" in task.content
    assert "failed after their retries, so their part of the report is missing: web search." in (
        task.content
    )


def test_an_object_that_was_not_investigated_is_marked_and_cites_its_map_data(monkeypatch):
    state = STATE.model_copy(update={"findings": []})
    text, writer = write(monkeypatch, state, "A site, not investigated [osm-way-1].")
    assert "Finding: not investigated." in writer.requests[0][-1].content
    assert "Sources:\n1. OpenStreetMap\n" in text


@pytest.mark.parametrize(
    "citation, told",
    [
        ("[osm-way-9]", "[osm-way-9]"),
        ("[osm-way-1, osm-way-9]", "[osm-way-1, osm-way-9]"),
        ("[osm-way-1](https://made-up.example)", "https://made-up.example)"),
        ("[[osm-way-1]](https://made-up.example)", "]("),
        ("[osm-way-1]\n\n[osm-way-1]: https://made-up.example", "]:"),
        ("(see www.made-up.example)", "www.made-up.example)"),
        ("[here]", "[here]"),
        ("at osm-way-1 [osm-way-1]", "osm-way-1"),
    ],
    ids=[
        "unknown",
        "two in one",
        "a link",
        "a link around",
        "a link definition",
        "a url",
        "not an id",
        "an id in the text",
    ],
)
def test_a_draft_with_a_wrong_citation_is_written_again(monkeypatch, citation, told):
    text, writer = write(monkeypatch, STATE, f"A site {citation}.", "A site [osm-way-1].")
    assert "A site [1, 2]." in text and "made-up" not in text
    assert told in writer.requests[1][-1].content


def test_wrong_citations_in_every_draft_stop_the_run(monkeypatch):
    drafts = ["A site [osm-way-9]."] * REPORT_ATTEMPTS
    with pytest.raises(ReportError):
        write(monkeypatch, STATE, *drafts)


def test_with_no_objects_the_report_has_no_sources(monkeypatch):
    state = RunState(property=Address(text="Freiheit 22, 13597 Berlin"))
    text, writer = write(monkeypatch, state)
    assert "No object of the checked kinds was found" in writer.requests[0][-1].content
    assert "Sources:" not in text and text.endswith(report.OSM_CREDIT)


def journey(id: str, direction, outcome, minutes: float | None = None) -> Journey:
    duration = None if minutes is None else dt.timedelta(minutes=minutes)
    return Journey(destination_id=id, direction=direction, outcome=outcome, mean_duration=duration)


def test_code_adds_each_journey_with_its_destination_direction_and_duration(monkeypatch):
    def destination(id: str, name: str, leave_home: dt.time, leave_place: dt.time) -> Destination:
        address = Address(text=f"{name} 1", coordinates=Coordinates(lat=52.5, lon=13.4))
        return Destination(
            id=id, name=name, address=address, leave_home=leave_home, leave_place=leave_place
        )

    state = STATE.model_copy(
        update={
            "destinations": [
                destination("destination-1", "work", dt.time(7, 40), dt.time(18, 10)),
                destination("destination-2", "the gym", dt.time(19), dt.time(21, 5)),
            ],
            "journeys": [
                journey("destination-2", "back", "unavailable"),
                journey("destination-1", "there", "found", 50.4),
                journey("destination-2", "there", "no route"),
                journey("destination-1", "back", "found", 47.5),
            ],
            "failures": ["transit"],
        }
    )
    text, writer = write(monkeypatch, state)
    assert "transit" not in writer.requests[0][-1].content  # the model does not write them
    assert (
        "Journeys by public transport on a normal weekday. Each time is the mean travel time of "
        "up to 3 connections that leave at the given time or later, without the wait for them:"
        "\n\n"
        "- work: there, leaving home at 07:40 or later, 50 min; back home, leaving it at 18:10 "
        "or later, 48 min.\n"
        "- the gym: there, leaving home at 19:00 or later, no connection found; back home, "
        "leaving it at 21:05 or later, not known, as the journey planner failed.\n\n"
        "The report covers"
    ) in text
    assert text.endswith(f"{report.OSM_CREDIT}\n{report.TRANSITOUS_CREDIT}")


def test_without_journeys_the_report_has_no_journeys_and_no_transit_credit(monkeypatch):
    text, _ = write(monkeypatch, STATE.model_copy(update={"destinations": []}))
    assert "Journeys" not in text and "transitous" not in text
    assert text.endswith(report.OSM_CREDIT)


@pytest.mark.parametrize("service", ["map", "plans"])
def test_a_source_failure_is_not_told_as_nothing_found(monkeypatch, service):
    state = RunState(property=Address(text="Freiheit 22, 13597 Berlin"), failures=[service])
    _, writer = write(monkeypatch, state)
    task = writer.requests[0][-1].content
    assert "was found" not in task
    assert f"so their part of the report is missing: {service}." in task


@pytest.mark.parametrize(
    "draft",
    ["The object osm-way-1 [osm-way-1].", "The object _osm-way-1_ [osm-way-1].", "__osm-way-1__"],
)
def test_an_id_in_the_text_is_told(draft):
    assert report.find_wrong_citations(draft, {"osm-way-1"}) == ["osm-way-1"]


def test_a_longer_id_in_the_text_is_not_a_known_one():
    assert report.find_wrong_citations("A site [osm-way-1], not osm-way-10.", {"osm-way-1"}) == []


@pytest.mark.parametrize("draft", ["A site [[osm-way-1]].", "A site [osm-way-1]]."])
def test_a_bracket_without_its_pair_is_told(draft):
    assert report.find_wrong_citations(draft, {"osm-way-1"})


RAILWAY = SITE.model_copy(
    update={"id": "osm-way-2", "details": {"railway": "rail", "category": "road_rail"}}
)
TRIAGED = Finding(
    map_object_id="osm-way-2",
    outcome="identified",
    identified_type="railway",
    status="operating",
    key_facts=["railway=rail"],
    evidence_id="overpass-1",
)
TWO = STATE.model_copy(update={"map_objects": [SITE, RAILWAY], "findings": [FOUND, TRIAGED]})


def test_a_draft_that_leaves_out_an_object_is_written_again(monkeypatch):
    first, second = "A site [osm-way-1].", "A site [osm-way-1]. A railway [osm-way-2]."
    text, writer = write(monkeypatch, TWO, first, second)
    assert "left out these objects" in writer.requests[1][-1].content
    assert "osm-way-2" in writer.requests[1][-1].content and "A railway [2]." in text


def test_a_draft_that_always_leaves_out_an_object_stops_the_run(monkeypatch):
    with pytest.raises(ReportError, match="osm-way-2"):
        write(monkeypatch, TWO, *["A site [osm-way-1]."] * REPORT_ATTEMPTS)


@pytest.mark.parametrize("between", ["", " "])
def test_citations_in_a_row_become_one(monkeypatch, between):
    text, _ = write(monkeypatch, TWO, f"A site and a railway [osm-way-1]{between}[osm-way-2].")
    assert "A site and a railway [1, 2]." in text


def test_citations_in_two_paragraphs_stay_apart(monkeypatch):
    text, _ = write(monkeypatch, TWO, "A site [osm-way-1]\n\n[osm-way-2] A railway.")
    assert "A site [1, 2]\n\n[2] A railway." in text


def test_the_report_says_which_kinds_it_checks(monkeypatch):
    text, _ = write(monkeypatch, STATE, "A site [osm-way-1].")
    assert "nearest 5 objects of each kind it checks: industrial and energy sites;" in text
