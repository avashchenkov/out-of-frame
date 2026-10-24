"""Coordinated deletion on disposable PostgreSQL/Redis, without the HTTP server or APIs."""

import asyncio
import datetime as dt
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from aegra_api.core import auth_handlers, database, orm
from aegra_api.core.database import db_manager
from aegra_api.core.redis_manager import redis_manager
from aegra_api.settings import DatabaseSettings, settings
from fastapi import HTTPException
from langgraph.graph import END, START, StateGraph
from sqlalchemy import text

from demo.backend import activity, auth, cleanup, config, storage

DATABASE = os.environ.get("OUT_OF_FRAME_TEST_DATABASE_URL")
REDIS = os.environ.get("OUT_OF_FRAME_TEST_REDIS_URL")
ROOT = Path(__file__).parents[3]
pytestmark = pytest.mark.skipif(
    not DATABASE or not REDIS, reason="needs disposable PostgreSQL/Redis"
)


@pytest.fixture(scope="module")
def schema(tmp_path_factory):
    folder = tmp_path_factory.mktemp("cleanup-schema")
    config_file = folder / "aegra.json"
    config_file.write_text('{"graphs": {}}')
    subprocess.run(
        [str(Path(sys.executable).with_name("aegra")), "db", "upgrade"],
        env=os.environ | {"DATABASE_URL": DATABASE, "AEGRA_CONFIG": str(config_file)},
        cwd=folder,
        check=True,
        capture_output=True,
    )
    with psycopg.connect(DATABASE) as connection:
        connection.execute((ROOT / "demo/db/schema.sql").read_text())


@pytest.fixture
def services(monkeypatch, schema):
    monkeypatch.setattr(settings, "db", DatabaseSettings(DATABASE_URL=DATABASE))
    monkeypatch.setattr(db_manager, "_database_url", settings.db.database_url)
    monkeypatch.setattr(settings.redis, "REDIS_URL", REDIS)
    monkeypatch.setattr(database, "load_store_config", lambda: {})
    monkeypatch.setattr(orm, "async_session_maker", None)
    monkeypatch.setattr(auth_handlers, "get_auth_instance", lambda: auth.auth)
    monkeypatch.setattr(activity, "_blocked_threads", set())

    @asynccontextmanager
    async def connected():
        await db_manager.initialize()
        await redis_manager.initialize()
        try:
            async with db_manager.engine.begin() as connection:
                await connection.execute(text("TRUNCATE thread, demo_identity, demo_day CASCADE"))
            yield
        finally:
            await redis_manager.close()
            await db_manager.close()

    return connected


async def seed_chat(*, expired=False):
    identity, thread_id, run_id = (str(uuid4()) for _ in range(3))
    expiry = dt.datetime.now(dt.UTC) + dt.timedelta(days=-1 if expired else 1)
    async with db_manager.engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO demo_identity(identity,expires_at,chats,thread_id,submissions) "
                "VALUES (:identity,:expiry,2,:thread,7)"
            ),
            {"identity": identity, "expiry": expiry, "thread": thread_id},
        )
        await connection.execute(
            text(
                "INSERT INTO demo_day(day,chats) "
                "VALUES ((now() AT TIME ZONE 'Europe/Berlin')::date,5) "
                "ON CONFLICT DO NOTHING"
            )
        )
    async with orm.get_session_maker()() as session:
        session.add(orm.Thread(thread_id=thread_id, user_id=identity))
        await session.flush()
        session.add(orm.Run(run_id=run_id, thread_id=thread_id, user_id=identity, status="running"))
        session.add(
            orm.ThreadTTL(thread_id=thread_id, strategy="delete", ttl_minutes=30, expires_at=expiry)
        )
        await session.commit()
    builder = StateGraph(dict)
    builder.add_node("report", lambda state: {"report": "PRIVATE_REPORT"})
    builder.add_edge(START, "report")
    builder.add_edge("report", END)
    graph = builder.compile(checkpointer=db_manager.get_checkpointer())
    await graph.ainvoke({}, {"configurable": {"thread_id": thread_id}})
    await seed_buffers(run_id)
    return identity, thread_id, run_id


async def seed_buffers(run_id):
    redis = redis_manager.get_client()
    prefix = settings.redis.REDIS_CHANNEL_PREFIX
    for kind in ("cache", "counter", "done"):
        await redis.set(f"{prefix}{kind}:{run_id}", "PRIVATE_SOURCE")
    await redis.rpush(settings.worker.WORKER_QUEUE_KEY, run_id)


async def assert_removed(thread_id, run_id):
    async with db_manager.engine.connect() as connection:
        for table in (
            "thread",
            "runs",
            "thread_ttl",
            "checkpoints",
            "checkpoint_writes",
            "checkpoint_blobs",
        ):
            assert (
                await connection.scalar(
                    text(f"SELECT count(*) FROM {table} WHERE thread_id=:id"), {"id": thread_id}
                )
                == 0
            )
    redis = redis_manager.get_client()
    assert not [key async for key in redis.scan_iter(f"*{run_id}*")]
    assert run_id not in await redis.lrange(settings.worker.WORKER_QUEUE_KEY, 0, -1)


@pytest.mark.parametrize("expired", [False, True])
def test_native_deletion_removes_all_data_without_refunding_quota(services, expired):
    async def scenario():
        async with services():
            identity, thread_id, run_id = await seed_chat(expired=expired)
            async with storage.locked(identity):
                assert await cleanup.erase(identity)
                assert await cleanup.erase(identity)
            await assert_removed(thread_id, run_id)
            saved = await storage.identity_row(identity)
            assert saved["thread_id"] is None and not saved["deleting"]
            assert saved["chats"] == 2 and saved["submissions"] == 7
            async with db_manager.engine.connect() as connection:
                assert await connection.scalar(text("SELECT chats FROM demo_day")) == 5

    asyncio.run(scenario())


def test_busy_nodes_leave_deletion_pending_until_a_later_sweep(services, monkeypatch):
    async def scenario():
        async with services():
            identity, thread_id, run_id = await seed_chat()
            monkeypatch.setattr(config, "DEMO_CANCEL_SECONDS", 0)
            monkeypatch.setattr(activity, "has_active_nodes", lambda thread: thread == thread_id)
            async with storage.locked(identity):
                assert not await cleanup.erase(identity)
            saved = await storage.identity_row(identity)
            assert saved["deleting"] and run_id in saved["run_ids"]
            with pytest.raises(HTTPException) as error:
                await auth.owned(identity, thread_id)
            assert error.value.status_code == 404
            snapshot = await db_manager.get_checkpointer().aget_tuple(
                {"configurable": {"thread_id": thread_id}}
            )
            assert snapshot is not None
            assert await redis_manager.get_client().exists(
                f"{settings.redis.REDIS_CHANNEL_PREFIX}cache:{run_id}"
            )
            monkeypatch.setattr(activity, "has_active_nodes", lambda thread: False)
            await cleanup.sweep()
            await assert_removed(thread_id, run_id)

    asyncio.run(scenario())


def test_active_worker_stops_before_native_deletion(services, monkeypatch):
    async def scenario():
        async with services():
            identity, thread_id, run_id = await seed_chat()
            started = asyncio.Event()

            async def worker():
                started.set()
                await asyncio.Event().wait()

            task = asyncio.create_task(worker())
            monkeypatch.setitem(cleanup.active_runs, run_id, task)
            native_delete = cleanup.delete_thread

            async def delete_after_worker(*args, **kwargs):
                assert task.done() and task.cancelled()
                return await native_delete(*args, **kwargs)

            monkeypatch.setattr(cleanup, "delete_thread", delete_after_worker)
            await started.wait()
            try:
                async with storage.locked(identity):
                    assert await cleanup.erase(identity)
                await assert_removed(thread_id, run_id)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_retry_keeps_run_ids_when_native_delete_commits_then_fails(services, monkeypatch):
    async def scenario():
        async with services():
            identity, thread_id, run_id = await seed_chat()
            native_delete = cleanup.delete_thread

            async def interrupted(*args, **kwargs):
                await native_delete(*args, **kwargs)
                raise OSError("interrupted after native commit")

            monkeypatch.setattr(cleanup, "delete_thread", interrupted)
            async with storage.locked(identity):
                with pytest.raises(OSError):
                    await cleanup.erase(identity)
            assert not auth.internal.get()
            saved = await storage.identity_row(identity)
            assert saved["deleting"] and run_id in saved["run_ids"]
            # The native run rows are gone; only the pending record remembers their buffers.
            await seed_buffers(run_id)
            monkeypatch.setattr(cleanup, "delete_thread", native_delete)
            await cleanup.sweep()
            await assert_removed(thread_id, run_id)

    asyncio.run(scenario())


def test_sweep_drops_expired_identity_but_keeps_other_chats(services):
    async def scenario():
        async with services():
            expired, thread_id, run_id = await seed_chat(expired=True)
            current, current_thread, _ = await seed_chat()
            await cleanup.sweep()
            await assert_removed(thread_id, run_id)
            assert await storage.identity_row(expired) is None
            assert (await storage.identity_row(current))["thread_id"] == current_thread

    asyncio.run(scenario())
