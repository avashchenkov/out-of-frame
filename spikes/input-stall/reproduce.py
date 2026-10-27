"""Offline failure injection, not a test of the live model.

Run from the repository root:
uv run --offline --no-sync python spikes/input-stall/reproduce.py
"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langgraph.types import Command

from out_of_frame import agent, conversation, geocoding
from out_of_frame.conversation import Change
from out_of_frame.state import RunState

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures" / "nominatim"
FIRST = "Please check Hauptstraße 1, Berlin."
COMBINED = "The first one, please. I travel nowhere regularly."
START = "Start then."
SELECTED = "Hauptstraße 1, 13591 Berlin"
READY = "I have everything needed and am ready to start."


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def run_case(label, combined_change):
    changes = {
        FIRST: Change(property_address="Hauptstraße 1, Berlin", destinations=None),
        COMBINED: combined_change,
        START: Change(property_address=None, destinations=None),
    }

    def extract_reply(messages):
        return {
            "raw": AIMessage("", response_metadata={"stop_reason": "end_turn"}),
            "parsed": changes[messages[-1].text],
        }

    def ask_reply(messages):
        text = (
            "Which address: 1. Hauptstraße 1, 13591 Berlin (Staaken); "
            "2. Hauptstraße 1, 10317 Berlin (Rummelsburg)? "
            "Where do you travel regularly, if anywhere?"
            if messages[-1].text == FIRST
            else READY
        )
        return AIMessage(text, response_metadata={"stop_reason": "end_turn"})

    def nominatim(query):
        if query == SELECTED:
            return fixture("hauptstrasse-1-staaken.json")
        assert query == "Hauptstraße 1, Berlin", query
        rummelsburg, staaken, *_ = fixture("hauptstrasse-1.json")
        return [staaken, rummelsburg]

    with (
        patch.object(
            conversation, "build_extract_model", lambda: SimpleNamespace(invoke=extract_reply)
        ),
        patch.object(
            conversation, "build_ask_model", lambda: SimpleNamespace(invoke=ask_reply)
        ),
        patch.object(conversation, "detect_language", lambda state: "English"),
        patch.object(geocoding, "call_nominatim", nominatim),
    ):
        graph, config = agent.compile_graph(), agent.start_thread()
        graph.invoke(agent.start(FIRST), config, interrupt_before=agent.RESEARCH_STARTS)
        assert agent.find_question(graph, config) is not None
        graph.invoke(Command(resume=COMBINED), config, interrupt_before=agent.RESEARCH_STARTS)
        state = RunState.model_validate(graph.get_state(config).values)
        missing = conversation.find_missing(state)
        if label == "both answers extracted":
            assert not missing
            assert state.destinations == [] and state.property.text == SELECTED
            assert agent.find_question(graph, config) is None
            assert set(graph.get_state(config).next) == set(agent.RESEARCH_STARTS)
            assert len([m for m in state.messages if m.type == "ai"]) == 1
        else:
            assert missing
            assert agent.find_question(graph, config) == READY
            graph.invoke(Command(resume=START), config, interrupt_before=agent.RESEARCH_STARTS)
            state = RunState.model_validate(graph.get_state(config).values)
            assert conversation.find_missing(state) == missing
            assert agent.find_question(graph, config) == READY
            assert graph.get_state(config).next == ("wait_for_answer",)
        print(json.dumps({
            "case": label,
            "missing": missing,
            "destinations": state.destinations,
            "next": graph.get_state(config).next,
            "waiting_for": agent.find_question(graph, config),
        }))


if __name__ == "__main__":
    run_case("both answers extracted", Change(property_address=SELECTED, destinations=[]))
    run_case("commute answer omitted", Change(property_address=SELECTED, destinations=None))
    run_case("address choice omitted", Change(property_address=None, destinations=[]))
