"""The investigation of one map object on the web: a LangGraph subgraph, see
docs/architecture.md#the-investigation-subgraph."""

import datetime as dt
import logging
from dataclasses import dataclass
from functools import cache
from typing import Literal, NamedTuple, Protocol

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from out_of_frame import finding
from out_of_frame.config import MODEL, TOOL_CAP
from out_of_frame.grounding import grounding_errors
from out_of_frame.state import Finding, InvestigationState, MapObject, Source, ToolCall, ToolResult

log = logging.getLogger(__name__)


class WebText(NamedTuple):
    url: str
    content: str  # a snippet from a search, or the full text of a page


class WebSearchFailed(Exception):
    """Web search or a page read failed, after the client's own retries."""


class Web(Protocol):
    """The web behind the model's two tools: Tavily from step 5.3, a stub in the tests. Each
    method raises WebSearchFailed if the service fails; nothing found is an empty list."""

    def search(self, query: str) -> list[WebText]: ...

    def extract(self, url: str) -> list[WebText]: ...


@dataclass(frozen=True)
class Context:
    """What a run gets besides its state. The date is not kept in the state, see
    docs/architecture.md#who-decides."""

    date: dt.date
    web: Web


def investigate(map_object: MapObject, date: dt.date, web: Web) -> InvestigationState:
    """Investigate one map object to the end: its finding passed the grounding check, or the
    object is unidentified."""
    start = InvestigationState(map_object=map_object, history=[], pages=[], finding=None)
    end = graph().invoke(start, context=Context(date, web))
    return InvestigationState.model_validate(end)


@cache
def graph():
    """The subgraph of the flowchart in docs/architecture.md, without the injection check."""
    builder = StateGraph(InvestigationState, context_schema=Context)
    builder.add_node(search_or_stop)
    builder.add_node(run_tool)
    builder.add_node(write_finding)
    builder.add_node(check_grounding)
    builder.add_conditional_edges(START, search_unless_at_the_cap)
    builder.add_conditional_edges("search_or_stop", run_tool_unless_stopped)
    builder.add_conditional_edges("run_tool", next_after_the_tool)
    builder.add_edge("write_finding", "check_grounding")
    builder.add_edge("check_grounding", END)
    return builder.compile()


def search_or_stop(state: InvestigationState, runtime: Runtime[Context]) -> dict:
    """The model makes one tool call, or answers without one when it has enough."""
    system = finding.render(
        "investigation.md.j2", cap=TOOL_CAP, date=runtime.context.date.isoformat()
    )
    answer = searcher().invoke([SystemMessage(system), *finding.messages(state)])
    if not answer.tool_calls:
        return {}
    call = answer.tool_calls[0]  # the only one: see searcher()
    entry = ToolCall.model_validate({"role": "model", "tool": call["name"], **call["args"]})
    return {"history": [entry]}


def run_tool(state: InvestigationState, runtime: Runtime[Context]) -> dict:
    """Code runs the model's tool call and gives each snippet or page an ID.

    TODO: in step 5.4, the prompt injection check drops flagged texts here, before they are
    stored: the history and the pages are only ever appended to.
    """
    call = state.history[-1]
    assert isinstance(call, ToolCall)  # run_tool_unless_stopped sends only a call here
    web = runtime.context.web
    try:
        texts = web.search(call.argument) if call.tool == "search" else web.extract(call.argument)
    except WebSearchFailed as error:
        log.warning("web search failed for %s: %s", state.map_object.id, error)
        return {"web_search_failed": True, "finding": Finding.unidentified(state.map_object.id)}
    first = len(state.pages) + 1
    pages = [
        Source(
            id=f"web-{first + n}",
            kind="web search",
            request=call.argument,
            url=text.url,
            content=text.content,
        )
        for n, text in enumerate(texts)
    ]
    return {"history": [ToolResult(role="tool", pages=[page.id for page in pages])], "pages": pages}


def write_finding(state: InvestigationState, runtime: Runtime[Context]) -> dict:
    return {"finding": finding.draft_finding(state, runtime.context.date)}


def check_grounding(state: InvestigationState) -> dict:
    """A finding that fails the grounding check makes the object unidentified: the model does
    not get another try."""
    assert state.finding is not None  # write_finding comes first
    errors = grounding_errors(state.finding, state.map_object, state.pages)
    if not errors:
        return {}
    log.info("finding for %s rejected: %s", state.map_object.id, "; ".join(errors))
    return {"finding": Finding.unidentified(state.map_object.id)}


def search_unless_at_the_cap(
    state: InvestigationState,
) -> Literal["search_or_stop", "write_finding"]:
    """At the cap, the finding is written without asking the model for another tool call."""
    calls = sum(isinstance(entry, ToolCall) for entry in state.history)
    return "write_finding" if calls >= TOOL_CAP else "search_or_stop"


def run_tool_unless_stopped(state: InvestigationState) -> Literal["run_tool", "write_finding"]:
    called = bool(state.history) and isinstance(state.history[-1], ToolCall)
    return "run_tool" if called else "write_finding"


def next_after_the_tool(
    state: InvestigationState,
) -> Literal["search_or_stop", "write_finding", "__end__"]:
    """A web search failure ends the run, at "__end__", LangGraph's END; otherwise the cap
    decides."""
    return "__end__" if state.web_search_failed else search_unless_at_the_cap(state)


@cache
def searcher():
    """The model with the web tools. It may answer without one to stop, and it makes one call
    at a time, so that code counts every call against the cap."""
    return ChatAnthropic(model=MODEL).bind_tools(
        finding.TOOLS, tool_choice="auto", parallel_tool_calls=False
    )
