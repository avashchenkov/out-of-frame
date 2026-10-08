"""Write the finding of an investigation: one model call, see
docs/architecture.md#the-investigation-subgraph."""

import datetime as dt
from functools import cache
from typing import Literal

import jinja2
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, create_model

from out_of_frame import research_scope
from out_of_frame.config import MODEL
from out_of_frame.state import Finding, InvestigationState, ToolCall

TASK = """\
Find out what map object {id} is and whether it is in use. Its map data, source ID {source_id}:
{map_text}"""

# The API needs every tool that the history uses. TODO: run them in step 5.2.
TOOLS = [
    {
        "name": "search",
        "description": "Search the web. Returns short snippets.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
    },
    {
        "name": "extract",
        "description": "Read the full text of one web page.",
        "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}},
    },
]


def write_finding(state: InvestigationState, date: dt.date) -> Finding:
    """Ask the model what the investigation found about its map object."""
    map_object = state.map_object
    template = templates().get_template("finding.md.j2")
    scope = research_scope.load()
    system = template.render(
        date=date.isoformat(),
        types=scope.identified_types,
        statuses=scope.finding_statuses,
    )
    request = [SystemMessage(system), *messages(state), HumanMessage("Write the finding.")]
    call = finder().invoke(request).tool_calls[0]
    # The ID is set by code, not taken from the model.
    return Finding.model_validate(call["args"] | {"map_object_id": map_object.id})


def messages(state: InvestigationState) -> list[BaseMessage]:
    """The investigation as a chat: the task, then each tool call and the pages it returned."""
    map_object = state.map_object
    pages = {page.id: page for page in state.pages}
    task = TASK.format(
        id=map_object.id, source_id=map_object.source_id, map_text=map_object.map_text().strip()
    )
    chat: list[BaseMessage] = [HumanMessage(task)]
    for n, entry in enumerate(state.history):
        if isinstance(entry, ToolCall):
            args = {"query": entry.query} if entry.tool == "search" else {"url": entry.url}
            chat.append(
                AIMessage("", tool_calls=[{"name": entry.tool, "args": args, "id": f"call-{n}"}])
            )
        else:  # a result always follows its call, see evals/load.py
            text = "\n\n".join(f"[{id}] {pages[id].url}\n{pages[id].content}" for id in entry.pages)
            chat.append(ToolMessage(text, tool_call_id=f"call-{n - 1}"))
    return chat


@cache
def finder():
    """The model, with the tools that the history uses and the Finding tool it must answer with."""
    return ChatAnthropic(model=MODEL).bind_tools([*TOOLS, finding_tool()], tool_choice="Finding")


def finding_tool() -> type[BaseModel]:
    """The Finding fields that the model fills in, with their descriptions. The type and the
    status are limited to the research scope's lists, so that the model can only choose one of
    them, or null. The map object's ID is left out: code sets it."""
    scope = research_scope.load()
    fields = {name: (f.annotation, f) for name, f in Finding.model_fields.items()}
    del fields["map_object_id"]
    for name, values in [
        ("identified_type", scope.identified_types),
        ("status", scope.finding_statuses),
    ]:
        fields[name] = (Literal[tuple(values)] | None, Finding.model_fields[name])
    return create_model("Finding", __doc__=Finding.__doc__, **fields)


@cache
def templates() -> jinja2.Environment:
    """The prompt templates in prompts/."""
    return jinja2.Environment(
        loader=jinja2.PackageLoader("out_of_frame", "prompts"),
        undefined=jinja2.StrictUndefined,  # a missing value fails instead of rendering empty
        trim_blocks=True,
        lstrip_blocks=True,
    )
