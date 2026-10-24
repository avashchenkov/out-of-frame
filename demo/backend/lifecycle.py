"""Startup guards, checkpoint types and coordinated cleanup for the Aegra service."""

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager

from aegra_api.core.auth_middleware import get_auth_instance
from aegra_api.core.database import db_manager
from aegra_api.services.executor import executor
from aegra_api.services.thread_ttl import get_thread_ttl_config
from aegra_api.settings import settings
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from sqlalchemy import text

from demo.backend import activity, auth, cleanup, config, contract
from demo.backend import logging as private_logging

log = logging.getLogger(__name__)


def reject_external_tracing():
    """Call while loading the app, before Aegra enables instrumentation."""
    if (
        settings.observability.OTEL_TARGETS
        or settings.observability.OTEL_CONSOLE_EXPORT
        or any(
            os.environ.get(name, "false").lower() in ("true", "1", "yes", "on")
            for name in (
                "LANGSMITH_TRACING",
                "LANGSMITH_TRACING_V2",
                "LANGCHAIN_TRACING",
                "LANGCHAIN_TRACING_V2",
            )
        )
    ):
        raise RuntimeError("External tracing is disabled for private demo conversations")


async def periodic():
    while True:
        await asyncio.sleep(config.DEMO_CLEANUP_SECONDS)
        try:
            await cleanup.sweep()
        except Exception:
            log.error("Demo cleanup failed; pending records will be retried")


@asynccontextmanager
async def lifespan(app):
    reject_external_tracing()
    contract.secret()
    private_logging.install()
    if get_auth_instance() is not auth.auth:
        raise RuntimeError("Demo authorization handlers must be enabled")
    if settings.db.DB_ECHO_LOG:
        raise RuntimeError("SQL body logging is disabled for private conversations")
    if not settings.redis.REDIS_BROKER_ENABLED or get_thread_ttl_config() is not None:
        raise RuntimeError(
            "Demo requires Redis and coordinated TTL cleanup, without the independent sweeper"
        )
    if (
        min(
            config.DEMO_DAILY_CHATS,
            config.DEMO_IDENTITY_CHATS,
            config.DEMO_LIFETIME_DAYS,
            config.DEMO_SUBMISSIONS,
            config.DEMO_MESSAGE_CHARS,
            config.DEMO_CLEANUP_SECONDS,
            config.DEMO_CANCEL_SECONDS,
        )
        <= 0
    ):
        raise RuntimeError("Demo limits must be positive")
    # Startup guard, not failover fencing: restart Aegra after database connection loss.
    # The deployment has one process; its worker tasks and sync-node barriers are local.
    async with db_manager.engine.connect() as owner:
        locked = await owner.scalar(
            text("SELECT pg_try_advisory_lock(hashtextextended('oof-demo-process',0))")
        )
        await owner.commit()
        if not locked:
            raise RuntimeError("Only one demo Aegra process may run against this database")
        task = None
        try:
            # Explicit container types only; do not allow arbitrary checkpoint imports.
            from out_of_frame import state
            from out_of_frame.agent import ObjectToInvestigate
            from out_of_frame.record import Record

            records = [
                value
                for value in vars(state).values()
                if isinstance(value, type) and issubclass(value, Record)
            ]
            db_manager.get_checkpointer().serde = JsonPlusSerializer(
                allowed_msgpack_modules=[*records, ObjectToInvestigate]
            )
            await cleanup.sweep()
            # Recovered work waits until expired content has been handled.
            activity.startup_cleanup_finished.set()
            task = asyncio.create_task(periodic())
            yield
        finally:
            activity.startup_cleanup_finished.clear()
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            # Aegra's outer lifespan normally stops workers after this context exits.
            # Drain them here so the next process cannot overlap our remaining work.
            await executor.stop()
            while activity.has_active_nodes():
                await asyncio.sleep(0.05)
            await owner.execute(
                text("SELECT pg_advisory_unlock(hashtextextended('oof-demo-process',0))")
            )
            await owner.commit()
