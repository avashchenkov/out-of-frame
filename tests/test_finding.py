"""The finding draft without the model: the request it builds and how it reads the answer."""

import datetime as dt

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import ValidationError

from out_of_frame import finding
from out_of_frame.state import (
    Coordinates,
    Finding,
    InvestigationState,
    MapObject,
    Source,
    ToolCall,
    ToolResult,
)

MAP_OBJECT = MapObject(
    id="obj-1",
    name="Test GmbH",
    details={"landuse": "industrial"},
    addresses=["Teststraße 1, 13597 Berlin"],
    coordinates=Coordinates(lat=52.5, lon=13.4),
    distance_from_property_m=100,
    source_id="map-1",
)
SNIPPET = Source(
    id="web-1",
    kind="web search",
    request="Teststraße 1 Berlin",
    url="https://example.org",
    content="Test GmbH makes parts at Teststraße 1.",
)
PAGE = Source(
    id="web-2",
    kind="web search",
    request="https://example.org",
    url="https://example.org",
    content="Test GmbH, Teststraße 1. We make parts.",
)
STATE = InvestigationState(
    map_object=MAP_OBJECT,
    history=[
        ToolCall(role="model", tool="search", query="Teststraße 1 Berlin"),
        ToolResult(role="tool", pages=["web-1"]),
        ToolCall(role="model", tool="extract", url="https://example.org"),
        ToolResult(role="tool", pages=["web-2"]),
    ],
    pages=[SNIPPET, PAGE],
    finding=None,
)
# What the model fills in, as the Finding tool's arguments.
ANSWER = {
    "outcome": "identified",
    "identified_type": "production",
    "status": "operating",
    "why_it_matters": "",
    "key_facts": ["Test GmbH makes parts"],
    "evidence_ids": ["web-1"],
}


class FakeModel:
    """Answers every request with a fixed Finding tool call and keeps the last request."""

    def __init__(self, args: dict):
        self.args = args
        self.request = []

    def invoke(self, request):
        self.request = request
        return AIMessage("", tool_calls=[{"name": "Finding", "args": self.args, "id": "call-f"}])


def test_the_history_becomes_tool_calls_and_their_results():
    task, search, snippets, extract, page = finding.messages(STATE)
    assert isinstance(task, HumanMessage) and "map-1" in task.content
    assert search.tool_calls[0]["args"] == {"query": "Teststraße 1 Berlin"}
    assert extract.tool_calls[0]["args"] == {"url": "https://example.org"}
    for call, result in [(search, snippets), (extract, page)]:
        assert isinstance(result, ToolMessage)
        assert result.tool_call_id == call.tool_calls[0]["id"]
    assert snippets.content.startswith("[web-1] https://example.org\n")
    assert page.content.startswith("[web-2] https://example.org\n")


def test_the_finding_tool_allows_only_a_listed_type_or_status():
    tool = finding.finding_tool()
    assert "map_object_id" not in tool.model_fields
    tool.model_validate(ANSWER)
    tool.model_validate(ANSWER | {"identified_type": None, "status": None})
    with pytest.raises(ValidationError):
        tool.model_validate(ANSWER | {"identified_type": "not a type"})
    with pytest.raises(ValidationError):
        tool.model_validate(ANSWER | {"status": "not a status"})


def test_the_request_has_the_prompt_the_history_and_the_last_instruction(monkeypatch):
    model = FakeModel(ANSWER)
    monkeypatch.setattr(finding, "finder", lambda: model)
    finding.draft_finding(STATE, dt.date(2026, 10, 3))
    system, *chat, last = model.request
    assert isinstance(system, SystemMessage)
    assert "2026-10-03" in system.content and "- production:" in system.content
    assert chat == finding.messages(STATE)
    assert last == HumanMessage("Write the finding.")


def test_the_finding_is_the_answer_with_the_map_object_id_from_code(monkeypatch):
    monkeypatch.setattr(finding, "finder", lambda: FakeModel(ANSWER | {"map_object_id": "obj-2"}))
    result = finding.draft_finding(STATE, dt.date(2026, 10, 3))
    assert result == Finding(map_object_id="obj-1", **ANSWER)


def test_an_answer_with_an_unlisted_type_fails(monkeypatch):
    monkeypatch.setattr(finding, "finder", lambda: FakeModel(ANSWER | {"identified_type": "x"}))
    with pytest.raises(ValidationError):
        finding.draft_finding(STATE, dt.date(2026, 10, 3))
