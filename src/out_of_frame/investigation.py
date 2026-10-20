"""The investigation of one map object on the web: a LangGraph subgraph, see
docs/architecture.md#the-investigation-subgraph."""

import datetime as dt
import logging
from dataclasses import dataclass
from functools import cache
from typing import Literal

from langchain_core.messages import SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from out_of_frame import finding, prompt_injection
from out_of_frame.chat_model import build_chat_model
from out_of_frame.config import PAGE_CHARS, TOOL_CAP
from out_of_frame.grounding import find_grounding_errors
from out_of_frame.state import (
    Finding,
    InvestigationState,
    MapObject,
    ObjectSourceKind,
    Source,
    ToolCall,
    ToolResult,
)
from out_of_frame.web_search import TOOLS, PageText, WebSearch, WebSearchError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Context:
    """What a run gets besides its state. The date is not kept in the state, see
    docs/architecture.md#who-decides."""

    date: dt.date
    web_search: WebSearch


def investigate(
    map_object: MapObject, source_kind: ObjectSourceKind, date: dt.date, web_search: WebSearch
) -> InvestigationState:
    """Investigate one map object to the end: its finding passed the grounding check, or the
    object is unidentified. The kind of its source says whether it is a plan."""
    start = InvestigationState.start(map_object, source_kind)
    end = build_graph().invoke(start, context=Context(date, web_search))
    return InvestigationState.model_validate(end)


@cache
def build_graph():
    """The subgraph of the flowchart in docs/architecture.md."""
    builder = StateGraph(InvestigationState, context_schema=Context)
    builder.add_node(search_or_stop)
    builder.add_node(run_tool)
    builder.add_node(write_finding)
    builder.add_node(check_grounding)
    builder.add_conditional_edges(START, search_unless_at_the_cap)
    builder.add_conditional_edges("search_or_stop", run_tool_unless_stopped)
    builder.add_conditional_edges("run_tool", route_after_the_tool)
    builder.add_edge("write_finding", "check_grounding")
    builder.add_edge("check_grounding", END)
    return builder.compile()


def search_or_stop(state: InvestigationState, runtime: Runtime[Context]) -> dict:
    """The model makes one tool call, or answers without one when it has enough."""
    call = choose_call(state, runtime.context.date)
    return {} if call is None else {"history": [call]}


def choose_call(state: InvestigationState, date: dt.date) -> ToolCall | None:
    """The one tool call that the model makes next, or None if it has enough."""
    system = finding.render(
        "investigation.md.j2",
        cap=TOOL_CAP,
        date=date.isoformat(),
        plan=state.source_kind == "plans",
    )
    answer = build_search_model().invoke([SystemMessage(system), *finding.build_chat(state)])
    if not answer.tool_calls:
        return None
    call = answer.tool_calls[0]  # the only one: see build_search_model()
    return ToolCall.model_validate({"role": "model", "tool": call["name"], **call["args"]})


def run_tool(state: InvestigationState) -> dict:
    """Code runs the model's tool call, drops each snippet or page that the prompt injection
    check flags, and gives the rest an ID. The check runs here, before anything is stored: the
    history and the pages are only ever appended to. It sees each text as the model will, cut.
    """
    call = state.history[-1]
    assert isinstance(call, ToolCall)  # run_tool_unless_stopped sends only a call here
    try:
        found = TOOLS[call.tool].invoke(call.args)
    except WebSearchError as error:
        log.warning("web search failed for %s: %s", state.map_object.id, error)
        return {"web_search_failed": True, "finding": Finding.unidentified(state.map_object.id)}
    texts = [PageText(text.url, cut_page(text.content)) for text in found]
    kept = []
    for text, injected in zip(texts, prompt_injection.flag_injections(texts), strict=True):
        if injected:
            log.warning("dropped a page with a prompt injection: %s", text.url)
        else:
            kept.append(text)
    first = len(state.pages) + 1
    pages = [
        Source(
            id=f"web-{first + n}",
            kind="web search",
            request=call.argument,
            url=text.url,
            content=text.content,
        )
        for n, text in enumerate(kept)
    ]
    return {"history": [ToolResult(role="tool", pages=[page.id for page in pages])], "pages": pages}


def cut_page(text: str) -> str:
    """The text up to PAGE_CHARS, so that a prompt stays short. The model is told when the rest
    is cut, so that it does not take a fact it cannot see for one that the page lacks."""
    if len(text) <= PAGE_CHARS:
        return text
    return text[:PAGE_CHARS] + f"\n[the page is cut at {PAGE_CHARS} characters]"


def write_finding(state: InvestigationState, runtime: Runtime[Context]) -> dict:
    return {"finding": finding.draft_finding(state, runtime.context.date)}


def check_grounding(state: InvestigationState) -> dict:
    """A finding that fails the grounding check makes the object unidentified: the model does
    not get another try."""
    assert state.finding is not None  # write_finding comes first
    errors = find_grounding_errors(state.finding, state.map_object, state.pages)
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


def route_after_the_tool(
    state: InvestigationState,
) -> Literal["search_or_stop", "write_finding", "__end__"]:
    """A web search failure ends the run, at "__end__", LangGraph's END; otherwise the cap
    decides."""
    return "__end__" if state.web_search_failed else search_unless_at_the_cap(state)


@cache
def build_search_model():
    """The model with the web tools. It may answer without one to stop, and it makes one call
    at a time, so that code counts every call against the cap."""
    return build_chat_model().bind_tools(
        list(TOOLS.values()), tool_choice="auto", parallel_tool_calls=False
    )
