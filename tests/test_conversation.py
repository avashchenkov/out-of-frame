"""The calls of the input phase, with stubbed models."""

import datetime as dt

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError

from evals.load import FIXTURES
from out_of_frame import conversation
from out_of_frame.conversation import Change, ConversationError, ExtractedDestination
from out_of_frame.state import Address, Coordinates, Destination, Message, RunState, Source

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
    """The extract model answers with the address and no change of the destinations, or with an
    answer that does not parse; returns the requests. A cut-off answer can still parse, as the
    parser repairs cut-off JSON."""
    requests = []

    def reply(request):
        requests.append(request)
        raw = AIMessage("", response_metadata={"stop_reason": stop_reason})
        parsed = Change(property_address=address, destinations=None) if parses else None
        return {"raw": raw, "parsed": parsed, "parsing_error": None if parses else "not JSON"}

    monkeypatch.setattr(conversation, "build_extract_model", lambda: RunnableLambda(reply))
    return requests


# The conversation as the model's own chat, with the agent's question as the model's turn.
CHAT = [
    HumanMessage("Hello"),
    AIMessage("Which property should I check?"),
    HumanMessage(LISTING),
]


def test_the_change_comes_from_the_conversation_and_the_input_so_far(monkeypatch):
    requests = stub_the_extract(monkeypatch, "Freiheit 22, 13597 Berlin")
    change = conversation.extract(STATE)
    assert change == Change(property_address="Freiheit 22, 13597 Berlin", destinations=None)
    [(system, *chat)] = requests
    assert "Only\n  the one to check is the property" in system.content
    assert "The property's address so far: Freiheit, Berlin" in system.content
    assert "The places the user travels to so far:\nnot given yet\n" in system.content
    assert chat == CHAT


WORK = Destination(
    id="destination-1",
    name="work",
    address=Address(text="Karl-Marx-Allee 3, 10178 Berlin"),
    leave_home=dt.time(7, 45),
)


@pytest.mark.parametrize(
    "destinations, shown",
    [
        ([], "none: the user travels nowhere regularly\n"),
        (
            [WORK, Destination(id="destination-2", name="gym")],
            "- destination-1: work; address: Karl-Marx-Allee 3, 10178 Berlin; leaves home for it "
            "at 07:45; leaves it for home at not given\n"
            "- destination-2: gym; address: not given; leaves home for it at not given; leaves it "
            "for home at not given\n",
        ),
    ],
    ids=["nowhere", "two places"],
)
def test_the_model_sees_the_places_so_far_with_their_ids(monkeypatch, destinations, shown):
    requests = stub_the_extract(monkeypatch, None)
    conversation.extract(STATE.model_copy(update={"destinations": destinations}))
    [(system, *_)] = requests
    assert f"The places the user travels to so far:\n{shown}\nRules:" in system.content


def extracted(name, id=None, address=None, leave_home=None, leave_place=None):
    return ExtractedDestination(
        id=id, name=name, address=address, leave_home=leave_home, leave_place=leave_place
    )


def test_a_change_without_destinations_leaves_them_and_a_new_address_has_no_coordinates():
    change = Change(property_address="Freiheit 22, 13597 Berlin", destinations=None)
    state = RunState(property=Address(text="Freiheit, Berlin"), destinations=[WORK])
    assert conversation.apply(change, state) == {
        "property": Address(text="Freiheit 22, 13597 Berlin")
    }
    assert conversation.apply(Change(property_address=None, destinations=None), state) == {}


def test_an_empty_list_says_that_the_user_travels_nowhere():
    change = Change(property_address=None, destinations=[])
    assert conversation.apply(change, RunState(destinations=[WORK])) == {"destinations": []}


def test_new_places_get_ids_from_code_and_their_times():
    change = Change(
        property_address=None,
        destinations=[
            extracted("work", address="Karl-Marx-Allee 3, 10178 Berlin", leave_home="07:45"),
            extracted("gym", leave_place="21:05"),
        ],
    )
    assert conversation.apply(change, RunState()) == {
        "destinations": [
            WORK,
            Destination(id="destination-2", name="gym", leave_place=dt.time(21, 5)),
        ]
    }


def test_a_correction_changes_only_its_field_and_keeps_the_other_place():
    gym = Destination(id="destination-2", name="gym", leave_home=dt.time(18))
    change = Change(
        property_address=None,
        destinations=[
            extracted("work", id="destination-1", leave_home="08:10"),
            extracted("gym", id="destination-2"),
        ],
    )
    corrected = WORK.model_copy(update={"leave_home": dt.time(8, 10)})
    state = RunState(destinations=[WORK, gym])
    assert conversation.apply(change, state) == {"destinations": [corrected, gym]}


def test_a_dropped_place_is_gone_and_the_other_keeps_its_id():
    gym = Destination(id="destination-2", name="gym")
    change = Change(property_address=None, destinations=[extracted("gym", id="destination-2")])
    assert conversation.apply(change, RunState(destinations=[WORK, gym])) == {"destinations": [gym]}


def test_an_unknown_or_repeated_id_gets_a_new_one_that_no_place_has():
    change = Change(
        property_address=None,
        destinations=[
            extracted("school", id="destination-7"),
            extracted("work", id="destination-1"),
            extracted("work again", id="destination-1"),
        ],
    )
    [school, work, again] = conversation.apply(change, RunState(destinations=[WORK]))[
        "destinations"
    ]
    assert (school.id, work, again.id) == ("destination-2", WORK, "destination-3")


def test_a_time_as_the_user_writes_it_is_a_clock_time_too():
    change = Change(property_address=None, destinations=[extracted("work", leave_home="7:45")])
    [work] = conversation.apply(change, RunState())["destinations"]
    assert work.leave_home == dt.time(7, 45)


@pytest.mark.parametrize("time", ["8am", "24:00", "07:45:00", "7.45"])
def test_a_time_that_is_not_a_clock_time_does_not_parse(time):
    with pytest.raises(ValidationError):
        extracted("work", leave_home=time)


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
    assert "say that they may travel nowhere" in system.content
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


def test_without_an_address_and_places_the_user_is_asked_for_both():
    assert conversation.find_missing(RunState()) == [
        "The user has not given the property's address.",
        "The user has not said where they travel regularly, if anywhere.",
    ]


def geocoded(text: str, source_id: str, fixture: str, coordinates=None) -> tuple[Address, Source]:
    content = (FIXTURES / "nominatim" / fixture).read_text(encoding="utf-8")
    source = Source(id=source_id, kind="geocoding", request=text, url="", content=content)
    return Address(text=text, coordinates=coordinates, source_id=source_id), source


FREIHEIT_22, FREIHEIT_SOURCE = geocoded(
    "Freiheit 22, 13597 Berlin", "nominatim-1", "freiheit-22.json", Coordinates(lat=1, lon=2)
)


def test_a_resolved_property_and_no_places_complete_the_input():
    state = RunState(property=FREIHEIT_22, destinations=[], sources=[FREIHEIT_SOURCE])
    assert conversation.find_missing(state) == []


def test_everything_missing_about_the_places_is_found_at_once():
    street, street_source = geocoded("Freiheit, Berlin", "nominatim-2", "freiheit-street.json")
    # Four buildings in Berlin: a place may be anywhere, so the reason does not say "in Berlin".
    several, several_source = geocoded("Hauptstraße 1", "nominatim-3", "hauptstrasse-1.json")
    potsdam, potsdam_source = geocoded(
        "Am Kanal 47, 14467 Potsdam",
        "nominatim-4",
        "am-kanal-47-potsdam.json",
        Coordinates(lat=52.3971923, lon=13.0592866),
    )
    state = RunState(
        property=street,
        destinations=[
            Destination(id="destination-1", name="work"),
            Destination(id="destination-2", name="gym", address=several, leave_home=dt.time(18)),
            Destination(
                id="destination-3",
                name="library",
                address=potsdam,  # resolved, so nothing is missing for it
                leave_home=dt.time(8),
                leave_place=dt.time(16),
            ),
        ],
        sources=[street_source, several_source, potsdam_source],
    )
    assert conversation.find_missing(state) == [
        "'Freiheit, Berlin' matches only a street or an area, not one building.",
        "The user has not given the address of 'work'.",
        "The user has not given the clock time when they leave home for 'work'.",
        "The user has not given the clock time when they leave 'work' for home.",
        "The address of 'gym': Several buildings match 'Hauptstraße 1': "
        "Hauptstraße 1, 10317 Berlin (Rummelsburg); Hauptstraße 1, 13591 Berlin (Staaken); "
        "Hauptstraße 1, 13159 Berlin (Blankenfelde); "
        "Hauptstraße 1, 13055 Berlin (Alt-Hohenschönhausen).",
        "The user has not given the clock time when they leave 'gym' for home.",
    ]
