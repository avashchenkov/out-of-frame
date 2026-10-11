"""The report with a stubbed model: what the model gets, and how code fills in the references."""

import datetime as dt
import re

import pytest
from langchain_core.messages import AIMessage

from out_of_frame import report
from out_of_frame.config import REPORT_ATTEMPTS
from out_of_frame.report import ReportError, fill_references, write_report
from out_of_frame.state import Address, Coordinates, Finding, MapObject, RunState, Source

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
    evidence_ids=["web-1"],
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
        ids = re.findall(r"^Object (\S+),", request[-1].content, re.MULTILINE)
        return AIMessage(" ".join(f"An object [{id}]." for id in ids) or "No object is listed.")


def write(monkeypatch, state=STATE, *drafts):
    """The report a person reads, from the draft the model writes."""
    writer = FakeWriter(*drafts)
    monkeypatch.setattr(report, "build_report_model", lambda: writer)
    return fill_references(write_report(state, DATE), state), writer


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
    from_the_map = FOUND.model_copy(update={"evidence_ids": ["overpass-1"]})
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
    assert "Object osm-way-1, 118 m from the property" in task.content
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
    ],
    ids=[
        "unknown",
        "two in one",
        "a link",
        "a link around",
        "a link definition",
        "a url",
        "not an id",
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
    assert "No unnamed industrial area was found" in writer.requests[0][-1].content
    assert "Sources:" not in text and text.endswith(report.OSM_CREDIT)


def test_a_map_failure_is_not_told_as_nothing_found(monkeypatch):
    state = RunState(property=Address(text="Freiheit 22, 13597 Berlin"), failures=["map"])
    _, writer = write(monkeypatch, state)
    task = writer.requests[0][-1].content
    assert "was found" not in task
    assert "so their part of the report is missing: map." in task
