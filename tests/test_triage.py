"""Triage of one map object, with a stubbed model."""

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from out_of_frame import research_scope, triage
from out_of_frame.state import Coordinates, Finding, MapObject

AIRPORT = MapObject(
    id="osm-way-859790021",
    name="Flughafen Berlin Brandenburg",
    details={"aeroway": "aerodrome", "iata": "BER", "category": "airport"},
    addresses=[],
    coordinates=Coordinates(lat=52.3657654, lon=13.49691),
    distance_from_property_m=3000,
    source_id="overpass-1",
)
CLEAR = {
    "clear": True,
    "identified_type": "airport",
    "status": "operating",
    "key_facts": ["Flughafen Berlin Brandenburg"],
}
UNCLEAR = {"clear": False, "identified_type": None, "status": None, "key_facts": []}


def stub_the_triage(monkeypatch, answer=CLEAR, stop_reason="end_turn") -> list:
    """The triage model answers every request with the answer, or with one that does not parse
    if it is None; returns the requests."""
    requests = []

    def reply(request):
        requests.append(request)
        raw = AIMessage("", response_metadata={"stop_reason": stop_reason})
        parsed = None if answer is None else triage.build_answer_schema().model_validate(answer)
        return {"raw": raw, "parsed": parsed, "parsing_error": None if answer else "not JSON"}

    monkeypatch.setattr(triage, "build_triage_model", lambda: RunnableLambda(reply))
    return requests


def test_a_clear_object_gets_a_finding_that_rests_on_the_map(monkeypatch):
    requests = stub_the_triage(monkeypatch)
    assert triage.triage(AIRPORT) == Finding(
        map_object_id="osm-way-859790021",
        outcome="identified",
        evidence_id="overpass-1",
        identified_type="airport",
        status="operating",
        key_facts=["Flughafen Berlin Brandenburg"],
    )
    [(system, task)] = requests
    assert "airport: An airfield" in system.content and "operating: In use now." in system.content
    assert "- planned:" not in system.content  # code sends planned objects to investigation
    assert "aeroway=aerodrome" in task.content and "airport" not in task.content  # no category


def test_an_unclear_object_goes_to_investigation(monkeypatch):
    stub_the_triage(monkeypatch, UNCLEAR)
    assert triage.triage(AIRPORT) is None


def test_an_answer_cut_off_or_not_parsed_sends_the_object_to_investigation(monkeypatch):
    stub_the_triage(monkeypatch, stop_reason="max_tokens")
    assert triage.triage(AIRPORT) is None
    stub_the_triage(monkeypatch, answer=None)
    assert triage.triage(AIRPORT) is None


@pytest.mark.parametrize("missing", ["identified_type", "status", "key_facts"])
def test_a_clear_answer_without_a_type_a_status_or_a_key_fact_goes_to_investigation(
    monkeypatch, missing
):
    stub_the_triage(monkeypatch, CLEAR | {missing: [] if missing == "key_facts" else None})
    assert triage.triage(AIRPORT) is None


def test_triage_offers_only_the_types_of_its_categories_from_the_research_scope():
    scope = research_scope.load()
    assert set(triage.TYPES) <= set(scope.identified_types)
    assert set(triage.STATUSES) <= set(scope.finding_statuses)
    schema = triage.build_answer_schema().model_json_schema()
    types = schema["properties"]["identified_type"]["anyOf"][0]["enum"]
    assert types == ["wastewater plant", "airport", "major road", "railway"]
    assert schema["properties"]["status"]["anyOf"][0]["enum"] == ["operating", "closed"]
    assert list(schema["properties"])[-1] == "clear"  # decided after the rest
