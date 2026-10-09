"""The finding draft without the model: the request it builds and how it reads the answer."""

import datetime as dt

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableBinding
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
    assert isinstance(search, AIMessage) and isinstance(extract, AIMessage)
    assert search.tool_calls[0]["args"] == {"query": "Teststraße 1 Berlin"}
    assert extract.tool_calls[0]["args"] == {"url": "https://example.org"}
    for call, result, first_line in [
        (search, snippets, "[web-1] https://example.org\n"),
        (extract, page, "[web-2] https://example.org\n"),
    ]:
        assert isinstance(result, ToolMessage) and isinstance(result.content, str)
        assert result.tool_call_id == call.tool_calls[0]["id"]
        assert result.content.startswith(first_line)


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
    assert isinstance(last, HumanMessage)
    assert "Teststraße 1, 13597 Berlin" in last.content


@pytest.mark.parametrize(
    "name, addresses",
    [
        (None, ["Teststraße 1, 13597 Berlin"]),
        ("Test GmbH", []),
        ("Test GmbH", ["Teststraße 1, 13597 Berlin", "Teststraße 3, 13597 Berlin"]),
        (None, []),
    ],
)
def test_the_last_message_names_the_object(name, addresses):
    map_object = MAP_OBJECT.model_copy(update={"name": name, "addresses": addresses})
    text = finding.render("finding_instruction.md.j2", map_object=map_object)
    assert all(address in text for address in addresses)
    assert ("Its name: Test GmbH." in text) == (name is not None)
    assert "\n\n" not in text


def test_the_finding_is_the_answer_with_the_map_object_id_from_code(monkeypatch):
    monkeypatch.setattr(finding, "finder", lambda: FakeModel(ANSWER | {"map_object_id": "obj-2"}))
    result = finding.draft_finding(STATE, dt.date(2026, 10, 3))
    assert result == Finding.model_validate(ANSWER | {"map_object_id": "obj-1"})


def test_an_answer_with_an_unlisted_type_fails(monkeypatch):
    monkeypatch.setattr(finding, "finder", lambda: FakeModel(ANSWER | {"identified_type": "x"}))
    with pytest.raises(ValidationError):
        finding.draft_finding(STATE, dt.date(2026, 10, 3))


def test_an_answer_without_the_finding_tool_fails(monkeypatch):
    class SearchingModel:
        def invoke(self, request):
            call = {"name": "search", "args": {"query": "Teststraße 1"}, "id": "call-s"}
            return AIMessage("", tool_calls=[call])

    monkeypatch.setattr(finding, "finder", lambda: SearchingModel())
    with pytest.raises(finding.MissingFindingError):
        finding.draft_finding(STATE, dt.date(2026, 10, 3))


def test_the_finding_tool_is_asked_for_but_not_forced_so_that_the_model_can_think():
    finding.finder.cache_clear()
    bound = finding.finder()
    assert isinstance(bound, RunnableBinding)
    assert bound.kwargs["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert [tool["name"] for tool in bound.kwargs["tools"]] == ["search", "extract", "Finding"]
