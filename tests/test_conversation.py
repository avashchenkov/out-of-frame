"""The calls of the input phase, with stubbed models."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda

from out_of_frame import conversation
from out_of_frame.conversation import Change, ConversationError
from out_of_frame.state import Address, Message, RunState

LISTING = "Bright flat at Freiheit 22, 13597 Berlin. Viewings: our office, Hauptstraße 1."
STATE = RunState(
    messages=[
        Message(role="user", text="Hello"),
        Message(role="agent", text="Which property should I check?"),
        Message(role="user", text=LISTING),
    ],
    property=Address(text="Freiheit, Berlin"),
)


def stub_the_extract(monkeypatch, address: str | None, stop_reason="end_turn", parses=True):
    """The extract model answers with the address, or with an answer that does not parse;
    returns the requests. A cut-off answer can still parse, as the parser repairs cut-off JSON."""
    requests = []

    def reply(request):
        requests.append(request)
        raw = AIMessage("", response_metadata={"stop_reason": stop_reason})
        parsed = Change(property_address=address) if parses else None
        return {"raw": raw, "parsed": parsed, "parsing_error": None if parses else "not JSON"}

    monkeypatch.setattr(conversation, "build_extract_model", lambda: RunnableLambda(reply))
    return requests


# The conversation as the model's own chat, with the agent's question as the model's turn.
CHAT = [
    HumanMessage("Hello"),
    AIMessage("Which property should I check?"),
    HumanMessage(LISTING),
]


def test_the_address_comes_from_the_conversation_and_the_address_so_far(monkeypatch):
    requests = stub_the_extract(monkeypatch, "Freiheit 22, 13597 Berlin")
    assert conversation.extract(STATE) == "Freiheit 22, 13597 Berlin"
    [(system, *chat)] = requests
    assert "only the address of the property to check" in system.content
    assert "The property's address so far: Freiheit, Berlin" in system.content
    assert chat == CHAT


@pytest.mark.parametrize(
    "stop_reason, parses", [("max_tokens", True), ("end_turn", False)], ids=["cut off", "no parse"]
)
def test_an_answer_that_is_cut_off_or_does_not_parse_stops_the_run(
    monkeypatch, stop_reason, parses
):
    stub_the_extract(monkeypatch, "Freiheit 22", stop_reason, parses)
    with pytest.raises(ConversationError):
        conversation.extract(STATE)


def stub_the_ask(monkeypatch, text: str, stop_reason="end_turn") -> list:
    """The ask model answers with the text; returns the requests."""
    requests = []

    def reply(request):
        requests.append(request)
        return AIMessage(text, response_metadata={"stop_reason": stop_reason})

    monkeypatch.setattr(conversation, "build_ask_model", lambda: RunnableLambda(reply))
    return requests


def test_the_question_is_about_what_code_found_missing(monkeypatch):
    requests = stub_the_ask(monkeypatch, "  Which one do you mean?\n")
    missing = ["Several buildings in Berlin match 'Hauptstraße 1': A; B."]
    assert conversation.ask(STATE, missing) == "Which one do you mean?"
    [(system, *chat)] = requests
    assert "ask which one is meant" in system.content and f"- {missing[0]}" in system.content
    assert chat == CHAT


@pytest.mark.parametrize(
    "text, stop_reason",
    [("Which one do", "max_tokens"), ("", "refusal"), ("  ", "end_turn")],
    ids=["cut off", "refused", "empty"],
)
def test_a_question_that_is_cut_off_or_empty_stops_the_run(monkeypatch, text, stop_reason):
    stub_the_ask(monkeypatch, text, stop_reason)
    with pytest.raises(ConversationError):
        conversation.ask(STATE, ["The user has not given the property's address."])


def test_without_an_address_the_user_is_asked_for_it():
    assert conversation.find_missing(RunState()) == [
        "The user has not given the property's address."
    ]
