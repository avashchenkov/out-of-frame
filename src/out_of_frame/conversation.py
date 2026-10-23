"""The input phase: the model picks out the property's address and the places the user travels
to from the user's last message, code applies and checks them, and the model asks for what is
missing, see docs/architecture.md#one-run."""

import datetime as dt
import itertools
from functools import cache
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from out_of_frame import geocoding
from out_of_frame.chat_model import build_chat_model
from out_of_frame.finding import render
from out_of_frame.state import Address, Destination, RunState

# A clock time as the model gives it, such as 07:45, or 7:45 as the user may write it: the API
# shows the model this pattern but does not enforce it.
CLOCK_TIME = r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$"


class ConversationError(Exception):
    """A model answer in the input phase was cut off, is empty or does not parse. The model
    failed, so the run stops, see docs/architecture.md#failures."""


class ExtractedDestination(BaseModel):
    """A place that the user travels to regularly, as the user's last message leaves it."""

    id: str | None = Field(
        description="Its ID among the places so far, if it is one of them; null for a new one."
    )
    name: str = Field(
        description="The user's own word for the place, such as work or the gym, or else its "
        "address."
    )
    address: str | None = Field(
        description="Its address, if the user's last message gives it or changes it; null if "
        "it does not."
    )
    leave_home: str | None = Field(
        pattern=CLOCK_TIME,
        description="The clock time when the user leaves home for the place, as HH:MM, if the "
        "user's last message gives it or changes it; null if it does not.",
    )
    leave_place: str | None = Field(
        pattern=CLOCK_TIME,
        description="The clock time when the user leaves the place for home, as HH:MM, if the "
        "user's last message gives it or changes it; null if it does not.",
    )


class UserLanguage(BaseModel):
    """The language that the user wants the answers in."""

    language: str | None = Field(
        description="The language by its name in English; null if the messages do not show it."
    )


class Change(BaseModel):
    """What the user's last message adds to the input or changes in it."""

    property_address: str | None = Field(
        description="The property's address if the user's last message gives it or changes "
        "it; null if it does not."
    )
    destinations: list[ExtractedDestination] | None = Field(
        description="The places the user travels to regularly, the whole list as the user's "
        "last message leaves it, if that message adds, changes or drops one: an empty list if "
        "the user travels nowhere; null if the message changes none of them."
    )


def extract(state: RunState) -> Change:
    """What the user's last message gives or changes in the input."""
    system = SystemMessage(
        render("extract.md.j2", property=state.property, destinations=state.destinations)
    )
    answer: Any = build_extract_model().invoke([system, *build_chat(state.messages)])
    if answer["raw"].response_metadata.get("stop_reason") != "end_turn" or not answer["parsed"]:
        raise ConversationError("the answer about the input was cut off or does not parse")
    return answer["parsed"]


def apply(change: Change, state: RunState) -> dict:
    """The fields of the input that the change replaces. A new address has no coordinates yet:
    code geocodes it next. A place so far keeps its ID and each
    field that the change leaves null. A new place gets a new ID, and so does one with an ID
    that is not among the places so far, or that the change gives twice."""
    update: dict = {}
    if change.property_address is not None:
        update["property"] = Address(text=change.property_address)
    if change.destinations is None:
        return update
    known = {destination.id: destination for destination in state.destinations or []}
    olds = [
        None if extracted.id is None else known.pop(extracted.id, None)
        for extracted in change.destinations
    ]
    kept = {old.id for old in olds if old is not None}
    new_ids = (f"destination-{n}" for n in itertools.count(1) if f"destination-{n}" not in kept)
    destinations = []
    for extracted, old in zip(change.destinations, olds, strict=True):
        fields: dict = {"name": extracted.name}
        if extracted.address is not None:
            fields["address"] = Address(text=extracted.address)
        for name in ("leave_home", "leave_place"):
            if (time := getattr(extracted, name)) is not None:
                fields[name] = dt.datetime.strptime(time, "%H:%M").time()
        if old is None:
            destinations.append(Destination(id=next(new_ids), **fields))
        else:
            destinations.append(old.model_copy(update=fields))
    return update | {"destinations": destinations}


def detect_language(state: RunState) -> str | None:
    """The language that the user wants the answers in, by its name in English, as the model
    reads it from all of the user's messages; null if they do not show it. Each message is
    numbered, so that a pasted text with blank lines in it is not taken for several."""
    system = SystemMessage(render("language.md.j2"))
    texts = [message.text for message in state.messages if message.type == "human"]
    text = "\n\n".join(f"Message {n}:\n{text}" for n, text in enumerate(texts, 1))
    answer: Any = build_language_model().invoke([system, HumanMessage(text)])
    if answer["raw"].response_metadata.get("stop_reason") != "end_turn" or not answer["parsed"]:
        raise ConversationError("the answer about the language was cut off or does not parse")
    return answer["parsed"].language


def find_missing(state: RunState) -> list[str]:
    """Everything missing or unclear in the input, for one question to the user; empty when the
    input is complete and research can start."""
    sources = {source.id: source for source in state.sources}

    def explain(address: Address, berlin_only: bool) -> str | None:
        assert address.source_id is not None  # code geocodes every address it is given
        return geocoding.explain(address, sources[address.source_id], berlin_only=berlin_only)

    missing = []
    if state.property is None:
        missing.append("The user has not given the property's address.")
    elif reason := explain(state.property, berlin_only=True):
        missing.append(reason)
    if state.destinations is None:
        missing.append("The user has not said where they travel regularly, if anywhere.")
    for destination in state.destinations or []:
        name = repr(destination.name)
        if destination.address is None:
            missing.append(f"The user has not given the address of {name}.")
        elif reason := explain(destination.address, berlin_only=False):
            missing.append(f"The address of {name}: {reason}")
        if destination.leave_home is None:
            missing.append(
                f"The user has not given the clock time when they leave home for {name}."
            )
        if destination.leave_place is None:
            missing.append(
                f"The user has not given the clock time when they leave {name} for home."
            )
    return missing


def ask(state: RunState, missing: list[str]) -> str:
    """The question to the user about what code found missing."""
    system = SystemMessage(render("ask.md.j2", missing=missing, language=state.find_language()))
    answer = build_ask_model().invoke([system, *build_chat(state.messages)])
    question = answer.text.strip()
    if answer.response_metadata.get("stop_reason") != "end_turn" or not question:
        raise ConversationError("the question to the user was cut off or is empty")
    return question


def build_chat(messages: list[BaseMessage]) -> list[BaseMessage]:
    """The conversation as the model's own chat: the user's messages, and the agent's questions
    as the model's turns. It ends with the user's last message."""
    return list(messages)


@cache
def build_extract_model():
    """The model with native structured output, which leaves it its thinking, as in
    triage.build_triage_model."""
    return build_chat_model().with_structured_output(Change, method="json_schema", include_raw=True)


@cache
def build_language_model():
    """The model with native structured output, as in build_extract_model."""
    return build_chat_model().with_structured_output(
        UserLanguage, method="json_schema", include_raw=True
    )


@cache
def build_ask_model():
    return build_chat_model()
