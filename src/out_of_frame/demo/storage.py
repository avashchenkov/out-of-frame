"""PostgreSQL admission records. No messages, addresses or reports belong here."""

import asyncio
from contextlib import asynccontextmanager
from weakref import WeakValueDictionary

from aegra_api.core.database import db_manager
from sqlalchemy import text

_locks = WeakValueDictionary()


@asynccontextmanager
async def locked(identity: str):
    """The enforced single server process serialises admission and deletion across API commits.

    Waiting requests consume no database connection. The counters themselves are transactional.
    """
    lock = _locks.setdefault(identity, asyncio.Lock())
    async with lock:
        yield


async def identity_row(identity: str):
    async with db_manager.engine.connect() as conn:
        return (
            (
                await conn.execute(
                    text("SELECT * FROM demo_identity WHERE identity=:id"), {"id": identity}
                )
            )
            .mappings()
            .first()
        )
