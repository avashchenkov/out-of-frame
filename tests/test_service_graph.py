"""Persistence and browser message contract without external calls."""

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from out_of_frame import agent, conversation, report
from out_of_frame.investigation import Context
from out_of_frame.state import RunState
from tests.test_agent import DATE, FREIHEIT_22, stub_the_conversation, stub_the_sources
from tests.test_investigation import FakeWebSearch
from tests.test_report import FakeWriter


def test_an_external_checkpointer_survives_rebuilding_the_graph(monkeypatch):
    stub_the_sources(monkeypatch, overpass=[{"elements": [{"type": "count", "id": 0}] * 4}])
    stub_the_conversation(monkeypatch, {"Hello": None})
    monkeypatch.setattr(report, "build_report_model", FakeWriter)
    saver = InMemorySaver()
    config = agent.start_thread()
    context = Context(DATE, FakeWebSearch())
    first = agent.compile_graph(checkpointer=saver)
    first.invoke(agent.start("Hello"), config, context=context, durability="sync")
    assert agent.find_question(first, config) == "Question 1"
    second = agent.compile_graph(checkpointer=saver)
    assert second is not first
    second.invoke(Command(resume=FREIHEIT_22), config, context=context, durability="sync")
    state = RunState.model_validate(second.get_state(config).values)
    assert [(m.type, m.text) for m in state.messages[:-1]] == [
        ("human", "Hello"),
        ("ai", "Question 1"),
        ("human", FREIHEIT_22),
    ]
    assert state.messages[-1].id == "final-report"
    assert state.messages[-1].text == state.report
    assert agent.fill_references(state)["report"] == state.report
    second.update_state(config, agent.fill_references(state))
    assert sum(m.id == "final-report" for m in second.get_state(config).values["messages"]) == 1


def test_old_saved_conversations_still_load():
    state = RunState.model_validate(
        {"messages": [{"role": "user", "text": "Hello"}, {"role": "agent", "text": "Where?"}]}
    )
    assert isinstance(state.messages[0], HumanMessage)
    assert isinstance(state.messages[1], AIMessage)
    assert conversation.build_chat(state.messages) == state.messages
    assert RunState.model_validate_json(state.model_dump_json()) == state
