"""The stub agent of the local UI stack: the real graph's steps, without model or web calls."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from demo.backend import activity, graph_factory
from demo.stub import agent as stub_agent
from out_of_frame.agent import compile_graph

DEMO = Path(__file__).parents[2] / "demo"


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(stub_agent, "DELAY", 0)


def run(*texts):
    """The stub's state after the first message and each answer that follows it."""
    graph = stub_agent.compile_graph(checkpointer=InMemorySaver())
    thread = {"configurable": {"thread_id": texts[0]}}
    graph.invoke({"messages": [{"type": "human", "content": texts[0]}]}, thread)
    for text in texts[1:]:
        graph.invoke(Command(resume=text), thread)
    return graph.get_state(thread)


def test_the_stub_has_the_steps_and_edges_of_the_real_agent():
    def shape(graph):
        drawn = graph.get_graph()
        return drawn.nodes.keys(), {(e.source, e.target, e.conditional) for e in drawn.edges}

    stub = shape(stub_agent.compile_graph(checkpointer=False))
    real = shape(compile_graph(checkpointer=False, context_schema=None))
    assert stub == real


def test_a_chat_asks_about_trips_then_writes_a_report():
    state = run("Please check Torstraße 1, 10119 Berlin.")
    assert state.next == ("wait_for_answer",)
    assert "travel" in state.interrupts[0].value
    state = run("Please check Torstraße 1, 10119 Berlin.", "Nowhere.")
    assert not state.next
    report = state.values["messages"][-1]
    assert report.id == "final-report"
    assert report.text.startswith("# What lies around Torstraße 1, 10119 Berlin")
    assert state.values["failures"] == []


def test_a_message_without_an_address_gets_a_question_about_it():
    state = run("Is this flat quiet?")
    assert "address" in state.interrupts[0].value
    state = run("Is this flat quiet?", "Torstraße 1, I travel nowhere regularly.")
    assert state.values["messages"][-1].id == "final-report"


def test_fail_in_a_message_shows_source_failures():
    state = run("Check Torstraße 1, Berlin, fail. I travel nowhere regularly.")
    assert state.values["failures"] == ["transit", "web search"]


def test_crash_in_a_message_stops_the_first_run_and_a_retry_finishes():
    graph = stub_agent.compile_graph(checkpointer=InMemorySaver())
    thread = {"configurable": {"thread_id": "crash-chat"}}
    message = "Check Torstraße 1, Berlin, crash. I travel nowhere regularly."
    with pytest.raises(RuntimeError):
        graph.invoke({"messages": [{"type": "human", "content": message}]}, thread)
    graph.invoke(None, thread)
    assert graph.get_state(thread).values["messages"][-1].id == "final-report"


def test_the_stub_entry_point_builds_the_stub_for_reads():
    graph = asyncio.run(stub_agent.create_graph({}, SimpleNamespace(access_context="threads.read")))
    assert graph.checkpointer is False
    assert graph.get_graph().nodes["investigate_object"].data.func.__module__ == stub_agent.__name__


def test_the_stub_runs_only_chats_that_pass_the_real_ownership_check(monkeypatch):
    async def missing(identity):
        return None

    monkeypatch.setattr(graph_factory.storage, "identity_row", missing)
    ready = asyncio.Event()
    ready.set()
    monkeypatch.setattr(activity, "startup_cleanup_finished", ready)
    runtime = SimpleNamespace(
        access_context="threads.create_run", user=SimpleNamespace(identity="owner")
    )
    with pytest.raises(RuntimeError, match="conversation_unavailable"):
        asyncio.run(stub_agent.create_graph({"configurable": {"thread_id": str(uuid4())}}, runtime))


def test_the_runtime_code_and_config_never_name_the_stub():
    assert json.loads((DEMO / "aegra.json").read_text())["graphs"] == {
        "agent": "./backend/graph_factory.py:create_graph"
    }
    for module in (DEMO / "backend").glob("*.py"):
        assert "stub" not in module.read_text(encoding="utf-8"), module.name


def test_the_stub_config_differs_from_the_runtime_one_only_in_the_graph():
    runtime = json.loads((DEMO / "aegra.json").read_text())
    stub = json.loads((DEMO / "stub" / "aegra.json").read_text())
    assert stub.pop("graphs") == {"agent": "./agent.py:create_graph"}
    runtime.pop("graphs")
    assert stub == runtime


def recorded_report(example_id):
    example = next(e for e in stub_agent.recorded_examples() if e["id"] == example_id)
    return next(m["content"] for m in example["messages"] if m["id"] == "final-report")


def test_a_report_is_a_full_recorded_one_under_the_user_address():
    report = run("Please check Torstraße 1, 10119 Berlin. I travel nowhere regularly.")
    text = report.values["messages"][-1].text
    rest = recorded_report("corinthstrasse-60").split("\n", 1)[1]
    assert text == f"# What lies around Torstraße 1, 10119 Berlin\n{rest}"


def test_a_user_who_travels_gets_a_report_with_journeys():
    state = run("Please check Torstraße 1, 10119 Berlin. I work at Karl-Marx-Allee 3 at 8:00.")
    assert "\n## Journeys\n" in state.values["messages"][-1].text


def test_a_recorded_address_gets_its_own_report():
    state = run("Please check Oberhofer Weg 45, 12209 Berlin. I travel nowhere regularly.")
    assert state.values["messages"][-1].text == recorded_report("oberhofer-weg-45")


def test_any_answer_to_the_one_question_leads_to_the_report():
    state = run("hello", "no idea")
    assert state.values["messages"][-1].id == "final-report"
    state = run("check torstr. 1 please")
    assert "travel" in state.interrupts[0].value
