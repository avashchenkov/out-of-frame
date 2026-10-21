"""Triage: one model call for each map object that code does not send to investigation, see
docs/architecture.md#one-run. If the map data, with what the model knows, settle the object
without a conflict, the model writes its finding with the map's status; otherwise the object
goes to investigation. A triage finding rests on the map, and no web page is checked."""

import logging
from functools import cache
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, create_model

from out_of_frame import research_scope
from out_of_frame.chat_model import build_chat_model
from out_of_frame.finding import render
from out_of_frame.state import Finding, MapObject

log = logging.getLogger(__name__)

# The types that triage can give: one for each category that reaches it. Code sends every
# industrial object to investigation and settles every railway itself, so any other type would
# mean that the model disagrees with the tags, a conflict that leaves the object unclear.
TYPES = ("wastewater plant", "airport", "major road")
# The statuses that triage can give. Code sends an object under construction or proposed to
# investigation, so a tag that says so, but that code missed, leaves the object unclear.
STATUSES = ("operating", "closed")


def is_railway(map_object: MapObject) -> bool:
    return map_object.details["category"] == "road_rail" and "railway" in map_object.details


def settle_railway(map_object: MapObject) -> Finding:
    """A railway's finding from its map data alone, with no model: its type, and no status,
    since no page that the agent can search shows whether trains run on a line now."""
    return Finding(
        map_object_id=map_object.id,
        outcome="identified",
        evidence_id=map_object.source_id,
        identified_type="railway",
        status=None,
        key_facts=[f"railway={map_object.details['railway']}"],
    )


def triage(map_object: MapObject) -> Finding | None:
    """The object's finding if triage settles it, or None to send it to investigation."""
    answer = ask(map_object)
    finding = settle(map_object, answer)
    if finding is None:
        log.info("triage sends %s to investigation; its answer: %r", map_object.id, answer)
    return finding


def ask(map_object: MapObject) -> Any:
    """The model's answer about the object, or None if it was cut off or does not parse: the
    object then goes to investigation, where the web can still settle it."""
    scope = research_scope.load()
    statuses = {name: scope.finding_statuses[name] for name in STATUSES}
    types = {name: scope.identified_types[name] for name in TYPES}
    system = render("triage.md.j2", types=types, statuses=statuses)
    task = render("triage_task.md.j2", map_object=map_object)
    answer: Any = build_triage_model().invoke([SystemMessage(system), HumanMessage(task)])
    if answer["raw"].response_metadata.get("stop_reason") != "end_turn":
        return None
    return answer["parsed"]


def settle(map_object: MapObject, answer: Any) -> Finding | None:
    """The finding of a clear answer, with a type, a status and a key fact; None for any other
    answer, which sends the object to investigation."""
    if answer is None or not answer.clear:
        return None
    if answer.identified_type is None or answer.status is None or not answer.key_facts:
        return None
    return Finding(
        map_object_id=map_object.id,
        outcome="identified",
        evidence_id=map_object.source_id,
        identified_type=answer.identified_type,
        status=answer.status,
        key_facts=answer.key_facts,
    )


@cache
def build_triage_model():
    """The model with native structured output, which leaves it its thinking, as in
    prompt_injection.build_check_model."""
    return build_chat_model().with_structured_output(
        build_answer_schema(), method="json_schema", include_raw=True
    )


def build_answer_schema() -> type[BaseModel]:
    """The triage answer, with the type and the status limited to the research scope's lists.
    clear comes last, so that the model decides it after it has written the rest."""
    # Literal of a tuple, which a type checker cannot read.
    types: Any = Literal[TYPES]
    statuses: Any = Literal[STATUSES]
    fields: dict[str, Any] = {
        "identified_type": (
            types | None,
            Field(
                description="The type that the name and tags, with what you know, settle; "
                "null if they do not settle one."
            ),
        ),
        "status": (
            statuses | None,
            Field(
                description="The status that the tags show, never what you know: operating "
                "unless a tag says that it is disused, abandoned or closed; null if the tags do "
                "not settle it."
            ),
        ),
        "key_facts": (
            list[str],
            Field(
                description="One to three lines of the map data, copied word for word, that "
                "show what the object is, such as its name or a tag like railway=rail."
            ),
        ),
        "clear": (
            bool,
            Field(
                description="true only if the type and the status are both set and nothing "
                "conflicts; false otherwise."
            ),
        ),
    }
    return create_model("Triage", **fields)
