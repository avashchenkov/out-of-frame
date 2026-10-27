"""Bound commute work before geocoding or routing, with no external calls."""

import datetime as dt
from unittest.mock import Mock

import pytest
from langgraph.runtime import Runtime
from langgraph.types import Command

from out_of_frame import agent, conversation, geocoding, transit
from out_of_frame.conversation import Change, ExtractedDestination
from out_of_frame.investigation import Context
from out_of_frame.state import Destination, RunState
from tests.test_agent import DATE, FREIHEIT_22, POTSDAM, stub_the_conversation, stub_the_sources
from tests.test_conversation import FREIHEIT_22 as HOME
from tests.test_conversation import FREIHEIT_SOURCE
from tests.test_investigation import FakeWebSearch

LIMIT_QUESTION = "At most 2 commute destinations are allowed. Ask the user which ones to keep."


def places(count):
    return [
        ExtractedDestination(
            id=None,
            name=f"place {index}",
            address=POTSDAM,
            leave_home="08:00",
            leave_place="17:00",
        )
        for index in range(1, count + 1)
    ]


def setup_input(monkeypatch, changes, journeys=0):
    stub_the_sources(
        monkeypatch,
        {FREIHEIT_22: "freiheit-22.json", POTSDAM: "am-kanal-47-potsdam.json"},
        transitous=[[] for _ in range(journeys)],
    )
    asked = stub_the_conversation(monkeypatch)
    monkeypatch.setattr(conversation, "extract", lambda state: changes[state.messages[-1].text])
    geocodes = Mock(wraps=geocoding.call_nominatim)
    routes = Mock(wraps=transit.call_transitous)
    monkeypatch.setattr(geocoding, "call_nominatim", geocodes)
    monkeypatch.setattr(transit, "call_transitous", routes)
    return asked, geocodes, routes


@pytest.mark.parametrize("count", [3, 20])
@pytest.mark.parametrize("keep", [0, 1, 2])
def test_oversized_input_waits_without_source_calls_and_can_be_reduced(monkeypatch, count, keep):
    requested = places(count)
    # Keep the last places, not an automatically chosen prefix; IDs and times must survive.
    chosen = [
        item.model_copy(update={"id": f"destination-{index}"})
        for index, item in list(enumerate(requested, 1))[count - keep :]
    ]
    changes = {
        "many places": Change(property_address=FREIHEIT_22, destinations=requested),
        "keep them all": Change(property_address=None, destinations=None),
        "fewer places": Change(property_address=None, destinations=chosen),
    }
    asked, geocodes, routes = setup_input(monkeypatch, changes, journeys=keep * 2)
    graph, config = agent.compile_graph(), agent.start_thread()
    context = Context(DATE, FakeWebSearch())

    def invoke(value):
        graph.invoke(value, config, context=context, interrupt_before=agent.RESEARCH_STARTS)
        return RunState.model_validate(graph.get_state(config).values)

    state = invoke(agent.start("many places"))
    assert agent.find_question(graph, config) == "Question 1"
    assert asked == [[LIMIT_QUESTION]]
    assert len(state.destinations) == count  # Do not silently drop a requested destination.
    geocodes.assert_not_called()
    routes.assert_not_called()

    invoke(Command(resume="keep them all"))
    assert agent.find_question(graph, config) == "Question 2"
    assert asked == [[LIMIT_QUESTION], [LIMIT_QUESTION]]
    geocodes.assert_not_called()
    routes.assert_not_called()

    state = invoke(Command(resume="fewer places"))
    assert agent.find_question(graph, config) is None
    assert set(graph.get_state(config).next) == set(agent.RESEARCH_STARTS)
    assert [place.id for place in state.destinations] == [place.id for place in chosen]
    assert all(place.leave_place == dt.time(17) for place in state.destinations)
    assert [call.args[0] for call in geocodes.call_args_list] == [FREIHEIT_22, *([POTSDAM] * keep)]
    result = agent.plan_journeys(state, Runtime(context=context))
    assert len(result.get("journeys", [])) == keep * 2
    assert routes.call_count == keep * 2


def test_adding_a_third_place_in_a_later_message_also_stops_source_calls(monkeypatch):
    requested = places(3)
    changes = {
        "two places, times later": Change(
            property_address=FREIHEIT_22,
            destinations=[item.model_copy(update={"leave_place": None}) for item in requested[:2]],
        ),
        "add a third": Change(
            property_address=None,
            destinations=[
                item.model_copy(update={"id": f"destination-{index}" if index < 3 else None})
                for index, item in enumerate(requested, 1)
            ],
        ),
    }
    asked, geocodes, routes = setup_input(monkeypatch, changes)
    graph, config = agent.compile_graph(), agent.start_thread()
    graph.invoke(agent.start("two places, times later"), config)
    assert agent.find_question(graph, config) == "Question 1"
    assert geocodes.call_count == 3
    geocodes.reset_mock()

    graph.invoke(Command(resume="add a third"), config, interrupt_before=agent.RESEARCH_STARTS)
    assert agent.find_question(graph, config) == "Question 2"
    assert asked[-1] == [LIMIT_QUESTION]
    geocodes.assert_not_called()
    routes.assert_not_called()


def test_a_saved_oversized_state_cannot_start_transit_queries(monkeypatch):
    state = RunState(
        property=HOME,
        sources=[FREIHEIT_SOURCE],
        destinations=[
            Destination(
                id=f"destination-{index}",
                name=f"place {index}",
                address=HOME,
                leave_home=dt.time(8),
                leave_place=dt.time(17),
            )
            for index in range(3)
        ],
    )
    plan = Mock(return_value=[])
    monkeypatch.setattr(transit, "plan_journeys", plan)
    assert agent.check_input(state) == "ask_for_missing"
    with pytest.raises(ValueError, match="commute destinations"):
        agent.plan_journeys(state, Runtime(context=Context(DATE, FakeWebSearch())))
    plan.assert_not_called()


@pytest.mark.parametrize("limit", [0, -1])
def test_the_destination_limit_must_be_positive(monkeypatch, limit):
    monkeypatch.setattr(conversation, "MAX_DESTINATIONS", limit, raising=False)
    with pytest.raises(ValueError, match="OUT_OF_FRAME_MAX_DESTINATIONS"):
        agent.compile_graph()
