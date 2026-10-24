"""Repeatable cleanup around Aegra's native TTL and thread deletion."""

import asyncio
import datetime as dt
import json

from aegra_api.api.threads import delete_thread
from aegra_api.core.active_runs import active_runs
from aegra_api.core.database import db_manager
from aegra_api.core.orm import Run, _get_session_maker
from aegra_api.core.redis_manager import redis_manager
from aegra_api.models import User
from aegra_api.services.broker import broker_manager
from aegra_api.services.executor import executor
from aegra_api.services.streaming_service import streaming_service
from aegra_api.services.thread_ttl import prune_expired_threads_for_user
from aegra_api.settings import settings
from fastapi import HTTPException
from sqlalchemy import select, text, update

from demo.backend import activity, auth, config, storage


async def erase(identity: str) -> bool:
    """Delete the current chat after all work stops; the caller holds its identity lock.

    Return False on timeout or incomplete native deletion. Keep the pending marker
    and run IDs so the next cleanup can retry without losing track of Redis data.
    """
    identity_record = await storage.identity_row(identity)
    if not identity_record or not identity_record["thread_id"]:
        return True
    thread_id = identity_record["thread_id"]
    activity.block_thread(thread_id)
    async with _get_session_maker()() as session:
        run_ids = list(
            (await session.scalars(select(Run.run_id).where(Run.thread_id == thread_id))).all()
        )
    run_ids = list(set(run_ids) | set(identity_record["run_ids"]))
    async with db_manager.engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE demo_identity SET deleting=true, run_ids=CAST(:ids AS jsonb) "
                "WHERE identity=:id"
            ),
            {"id": identity, "ids": json.dumps(run_ids)},
        )
    # Terminal status prevents pending jobs and lease recovery from starting new execution.
    async with _get_session_maker()() as session:
        await session.execute(update(Run).where(Run.run_id.in_(run_ids)).values(status="error"))
        await session.commit()
    for run_id in run_ids:
        await streaming_service.cancel_run(run_id, emit_end_event=False)
    worker_tasks = {
        t for t, run_id in getattr(executor, "_job_tasks", {}).items() if run_id in run_ids
    }
    worker_tasks.update(active_runs[run_id] for run_id in run_ids if run_id in active_runs)
    for task in worker_tasks:
        if not task.done():
            task.cancel()
    deadline = asyncio.get_running_loop().time() + config.DEMO_CANCEL_SECONDS
    while any(not task.done() for task in worker_tasks) or activity.has_active_nodes(thread_id):
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(0.05)
    # Cancellation finalisers can have changed status after the first barrier.
    async with _get_session_maker()() as session:
        await session.execute(update(Run).where(Run.run_id.in_(run_ids)).values(status="error"))
        await session.commit()
    redis_client = redis_manager.get_client()
    for run_id in run_ids:
        pipeline = redis_client.pipeline()
        pipeline.lrem(settings.worker.WORKER_QUEUE_KEY, 0, run_id)
        prefix = settings.redis.REDIS_CHANNEL_PREFIX
        pipeline.delete(*(f"{prefix}{kind}:{run_id}" for kind in ("cache", "counter", "done")))
        await pipeline.execute()
        broker_manager.remove_broker(run_id)
    token = auth.internal.set(True)
    try:
        async with _get_session_maker()() as session:
            if identity_record["expires_at"] <= dt.datetime.now(dt.UTC):
                await prune_expired_threads_for_user(session, user_id=identity)
            else:
                try:
                    await delete_thread(thread_id, user=User(identity=identity), session=session)
                except HTTPException as error:
                    if error.status_code != 404:
                        raise
        # Partial native deletion must not silently drop our retry bookkeeping.
        async with db_manager.engine.connect() as conn:
            remains = await conn.scalar(
                text("SELECT 1 FROM thread WHERE thread_id=:t"), {"t": thread_id}
            )
        if remains:
            return False
    finally:
        auth.internal.reset(token)
    async with db_manager.engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE demo_identity SET thread_id=NULL, deleting=false, run_ids='[]'::jsonb "
                "WHERE identity=:id"
            ),
            {"id": identity},
        )
    return True


async def sweep(identity: str | None = None):
    """Retry pending/expired chats, or delete one operator-selected identity's chat."""
    async with db_manager.engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT identity FROM demo_identity WHERE "
                        + ("identity=:id" if identity else "expires_at<=now() OR deleting")
                    ),
                    {"id": identity},
                )
            )
            .scalars()
            .all()
        )
    pending = 0
    for visitor in rows:
        async with storage.locked(visitor):
            if not await erase(visitor):
                pending += 1
    async with db_manager.engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM demo_identity WHERE expires_at<=now() "
                "AND thread_id IS NULL AND NOT deleting"
            )
        )
        await conn.execute(
            text("DELETE FROM demo_day WHERE day < (now() AT TIME ZONE 'Europe/Berlin')::date")
        )
    return {"pending": pending}
