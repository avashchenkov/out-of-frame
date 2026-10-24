"""Server-owned graph context and deletion barriers, without external calls."""

import asyncio
import datetime as dt
import threading
from types import SimpleNamespace
from typing import TypedDict
from unittest.mock import AsyncMock, Mock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.store.memory import InMemoryStore

from demo.backend import activity, graph_factory


class State(TypedDict):
    value: str


def one_node(function, context):
    builder = StateGraph(State)
    builder.add_node("work", activity.wrap_node(context)(function))
    builder.add_edge(START, "work")
    builder.add_edge("work", END)
    return builder.compile(store=InMemoryStore())


def test_node_context_keeps_runtime_services_and_releases_failed_work():
    thread = str(uuid4())
    context = object()

    def work(state: State, runtime: Runtime):
        assert activity.has_active_nodes(thread)
        assert runtime.context is context
        assert runtime.store is graph.store
        assert runtime.execution_info is not None
        runtime.stream_writer("progress")
        raise ValueError("source_unavailable")

    graph = one_node(work, context)
    events = graph.stream(
        {"value": "input"}, {"configurable": {"thread_id": thread}}, stream_mode="custom"
    )
    assert next(events) == "progress"
    with pytest.raises(ValueError, match="source_unavailable"):
        list(events)
    assert not activity.has_active_nodes(thread)


def test_cancellation_keeps_sync_work_busy_and_blocking_stops_new_nodes():
    async def scenario():
        thread = str(uuid4())
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()

        def work(state: State):
            entered.set()
            try:
                assert release.wait(5), "test did not release the synchronous node"
                return {"value": "done"}
            finally:
                finished.set()

        graph = one_node(work, None)
        config = {"configurable": {"thread_id": thread}}
        task = asyncio.create_task(graph.ainvoke({"value": "input"}, config))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert activity.has_active_nodes(thread)
            activity.block_thread(thread)
            with pytest.raises(RuntimeError, match="conversation_unavailable"):
                await graph.ainvoke({"value": "retry"}, config)
        finally:
            release.set()
            assert await asyncio.to_thread(finished.wait, 5)
            # The node's finally runs just before the activity wrapper's finally.
            for _ in range(100):
                if not activity.has_active_nodes(thread):
                    break
                await asyncio.sleep(0.01)
            assert not activity.has_active_nodes(thread)

    asyncio.run(scenario())


@pytest.mark.parametrize("access", ["assistants.read", "threads.read", "threads.update"])
def test_inspection_does_not_build_external_clients_or_wait_for_startup(monkeypatch, access):
    def forbidden(*args, **kwargs):
        raise AssertionError("inspection must not access services")

    monkeypatch.setattr(graph_factory.storage, "identity_row", forbidden)
    monkeypatch.setattr(graph_factory, "TavilyWebSearch", forbidden)
    monkeypatch.setattr(activity, "startup_cleanup_finished", asyncio.Event())
    graph = asyncio.run(graph_factory.create_graph({}, SimpleNamespace(access_context=access)))
    assert graph.checkpointer is False
    assert "extract_input" in graph.get_graph().nodes


@pytest.mark.parametrize("invalid", ["missing", "other_thread", "deleting", "expired"])
def test_execution_rejects_unavailable_chats_before_building_clients(monkeypatch, invalid):
    thread = str(uuid4())
    row = {
        "thread_id": thread,
        "deleting": invalid == "deleting",
        "expires_at": dt.datetime.now(dt.UTC)
        + dt.timedelta(days=-1 if invalid == "expired" else 1),
    }
    if invalid == "other_thread":
        row["thread_id"] = str(uuid4())
    lookup = AsyncMock(return_value=None if invalid == "missing" else row)
    client = Mock(side_effect=AssertionError("rejected execution must not build clients"))
    monkeypatch.setattr(graph_factory.storage, "identity_row", lookup)
    monkeypatch.setattr(graph_factory, "TavilyWebSearch", client)
    ready = asyncio.Event()
    ready.set()
    monkeypatch.setattr(activity, "startup_cleanup_finished", ready)
    runtime = SimpleNamespace(
        access_context="threads.create_run", user=SimpleNamespace(identity="owner")
    )
    with pytest.raises(RuntimeError, match="conversation_unavailable"):
        asyncio.run(graph_factory.create_graph({"configurable": {"thread_id": thread}}, runtime))
    lookup.assert_awaited_once_with("owner")
    client.assert_not_called()


def test_execution_waits_for_cleanup_and_builds_context_per_invocation(monkeypatch):
    async def scenario():
        thread = str(uuid4())
        lookup = AsyncMock(
            return_value={
                "thread_id": thread,
                "deleting": False,
                "expires_at": dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
            }
        )
        monkeypatch.setattr(graph_factory.storage, "identity_row", lookup)
        monkeypatch.setattr(graph_factory, "TavilyWebSearch", object)
        contexts = []
        wrap_node = activity.wrap_node

        def wrapped(context):
            contexts.append(context)
            return wrap_node(context)

        monkeypatch.setattr(graph_factory.activity, "wrap_node", wrapped)
        ready = asyncio.Event()
        monkeypatch.setattr(activity, "startup_cleanup_finished", ready)
        runtime = SimpleNamespace(
            access_context="threads.create_run", user=SimpleNamespace(identity="owner")
        )
        config = {"configurable": {"thread_id": thread}}
        task = asyncio.create_task(graph_factory.create_graph(config, runtime))
        await asyncio.sleep(0)
        assert not task.done()
        lookup.assert_not_awaited()
        ready.set()
        first = await task
        second = await graph_factory.create_graph(config, runtime)
        assert first is not second
        assert first.checkpointer is second.checkpointer is False
        assert first.get_graph().nodes.keys() == second.get_graph().nodes.keys()
        assert len(contexts) == 2 and contexts[0] is not contexts[1]
        assert contexts[0].web_search is not contexts[1].web_search
        assert all(
            context.date == dt.datetime.now(ZoneInfo("Europe/Berlin")).date()
            for context in contexts
        )

    asyncio.run(scenario())
