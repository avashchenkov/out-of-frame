"""The input phase: the model picks out the property's address from the user's last message,
code checks it, and the model asks for what is missing, see docs/architecture.md#one-run.

TODO: the destinations and their departure times, with the journeys (step 9).
"""

from functools import cache
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from out_of_frame import geocoding
from out_of_frame.config import MODEL
from out_of_frame.finding import render
from out_of_frame.state import Message, RunState


class ExtractError(Exception):
    """The extract answer was cut off or does not parse. The model failed, so the run stops, see
    docs/architecture.md#failures."""


class Change(BaseModel):
    """What the user's last message adds to the input or changes in it."""

    property_address: str | None = Field(
        description="The property's address if the user's last message gives it or changes "
        "it; null if it does not."
    )


def extract(state: RunState) -> str | None:
    """The property's address from the user's last message, if it gives a new one."""
    system = SystemMessage(render("extract.md.j2", property=state.property))
    answer: Any = build_extract_model().invoke([system, *build_chat(state.messages)])
    if answer["raw"].response_metadata.get("stop_reason") != "end_turn" or not answer["parsed"]:
        raise ExtractError("the answer about the address was cut off or does not parse")
    return answer["parsed"].property_address


def find_missing(state: RunState) -> list[str]:
    """What is missing or unclear in the input, for the question to the user; empty when the
    input is complete and research can start."""
    if state.property is None:
        return ["The user has not given the property's address."]
    sources = {source.id: source for source in state.sources}
    assert state.property.source_id is not None  # code geocodes every address it is given
    reason = geocoding.explain(state.property, sources[state.property.source_id])
    return [] if reason is None else [reason]


def ask(state: RunState, missing: list[str]) -> str:
    """The question to the user about what code found missing."""
    system = SystemMessage(render("ask.md.j2", missing=missing))
    return build_ask_model().invoke([system, *build_chat(state.messages)]).text.strip()


def build_chat(messages: list[Message]) -> list[BaseMessage]:
    """The conversation as the model's own chat: the user's messages, and the agent's questions
    as the model's turns. It ends with the user's last message."""
    return [
        HumanMessage(message.text) if message.role == "user" else AIMessage(message.text)
        for message in messages
    ]


@cache
def build_extract_model():
    """The model with native structured output, which leaves it its thinking, as in
    triage.build_triage_model."""
    return ChatAnthropic(model=MODEL).with_structured_output(
        Change, method="json_schema", include_raw=True
    )


@cache
def build_ask_model():
    return ChatAnthropic(model=MODEL)
