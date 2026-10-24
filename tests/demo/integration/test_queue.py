"""Aegra's real Redis queue and worker; graph work replaces database leases and APIs."""

import asyncio
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from aegra_api.core.redis_manager import redis_manager
from aegra_api.services.worker_executor import WorkerExecutor
from aegra_api.settings import settings
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from redis.asyncio import Redis

REDIS = os.environ.get("OUT_OF_FRAME_TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(not REDIS, reason="needs disposable Redis")


@pytest.mark.parametrize("outcome", ["success", "interrupted", "error"])
def test_native_queue_starts_next_run_after_current_run_releases_slot(monkeypatch, outcome):
    async def scenario():
        client = Redis.from_url(REDIS, decode_responses=True)
        queue = f"oof-test-queue:{uuid4()}"
        monkeypatch.setattr(redis_manager, "get_client", lambda: client)
        monkeypatch.setattr(settings.worker, "WORKER_COUNT", 1)
        monkeypatch.setattr(settings.worker, "N_JOBS_PER_WORKER", 1)
        monkeypatch.setattr(settings.worker, "WORKER_QUEUE_KEY", queue)
        executor = WorkerExecutor()
        first, second = str(uuid4()), str(uuid4())
        entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
        started, results = [], {}

        async def work(state):
            if state["wait"]:
                entered.set()
                await release.wait()
                if outcome == "interrupted":
                    interrupt("Where do you travel?")
                if outcome == "error":
                    raise RuntimeError("stub execution failed")
            return {"done": True}

        builder = StateGraph(dict)
        builder.add_node("work", work)
        builder.add_edge(START, "work")
        builder.add_edge("work", END)
        graph = builder.compile(checkpointer=InMemorySaver())

        async def execute(run_id, worker_name):
            started.append(run_id)
            results[run_id] = await graph.ainvoke(
                {"wait": run_id == first}, {"configurable": {"thread_id": run_id}}
            )
            if run_id == second:
                finished.set()

        monkeypatch.setattr(executor, "_execute_with_lease", execute)
        try:
            await executor.start()
            await executor.submit(SimpleNamespace(identity=SimpleNamespace(run_id=first)))
            await asyncio.wait_for(entered.wait(), 5)
            await executor.submit(SimpleNamespace(identity=SimpleNamespace(run_id=second)))
            assert await client.lrange(queue, 0, -1) == [second]
            assert started == [first]
            release.set()
            await asyncio.wait_for(finished.wait(), 5)
            assert started == [first, second]
            if outcome == "interrupted":
                assert results[first]["__interrupt__"]
            assert results[second] == {"done": True}
        finally:
            release.set()
            await executor.stop()
            await client.delete(queue)
            await client.aclose()

    asyncio.run(scenario())
