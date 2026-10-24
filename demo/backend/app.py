"""Aegra extension for private chat admission, replacement, deletion and status."""

import datetime as dt
from typing import Annotated
from uuid import uuid4
from zoneinfo import ZoneInfo

from aegra_api.api.runs import create_run
from aegra_api.api.threads import create_thread
from aegra_api.core.auth_deps import require_auth
from aegra_api.core.database import db_manager
from aegra_api.core.orm import _get_session_maker
from aegra_api.models import RunCreate, ThreadCreate, User
from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from demo.backend import auth, cleanup, config, contract, storage
from demo.backend.http_access import PrivateDemoAccess
from demo.backend.lifecycle import lifespan, reject_external_tracing

reject_external_tracing()

app = FastAPI(lifespan=lifespan)
app.add_middleware(PrivateDemoAccess)


@app.exception_handler(RequestValidationError)
async def invalid_request(request, error):
    return JSONResponse({"error": "invalid_request"}, status_code=422)


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    replace: bool = False


async def reserve_chat(identity):
    now = dt.datetime.now(dt.UTC)
    expiry = now + dt.timedelta(days=config.DEMO_LIFETIME_DAYS)
    day = now.astimezone(ZoneInfo("Europe/Berlin")).date()
    async with db_manager.engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO demo_identity(identity,expires_at) VALUES (:id,:expiry) "
                "ON CONFLICT DO NOTHING"
            ),
            {"id": identity, "expiry": expiry},
        )
        row = (
            (
                await conn.execute(
                    text("SELECT * FROM demo_identity WHERE identity=:id FOR UPDATE"),
                    {"id": identity},
                )
            )
            .mappings()
            .one()
        )
        if row["expires_at"] <= now:
            raise HTTPException(401, "identity_expired")
        if row["deleting"]:
            raise HTTPException(409, "deletion_pending")
        if row["chats"] >= config.DEMO_IDENTITY_CHATS:
            raise HTTPException(429, "identity_chats_exhausted")
        await conn.execute(
            text("INSERT INTO demo_day(day) VALUES (:day) ON CONFLICT DO NOTHING"), {"day": day}
        )
        changed = await conn.execute(
            text("UPDATE demo_day SET chats=chats+1 WHERE day=:day AND chats<:cap RETURNING chats"),
            {"day": day, "cap": config.DEMO_DAILY_CHATS},
        )
        if changed.scalar_one_or_none() is None:
            raise HTTPException(429, "daily_chats_exhausted")
        await conn.execute(
            text("UPDATE demo_identity SET chats=chats+1 WHERE identity=:id"), {"id": identity}
        )
    return row["expires_at"]


@app.post("/demo/chat")
async def new_chat(body: ChatInput, user: Annotated[User, Depends(require_auth)]):
    contract.validate_text(body.text)
    old = await storage.identity_row(user.identity)
    if old and old["thread_id"] and not body.replace:
        raise HTTPException(409, "chat_exists")
    expiry = await reserve_chat(user.identity)
    if old and old["thread_id"] and not await cleanup.erase(user.identity):
        raise HTTPException(409, "deletion_pending")
    thread_id = str(uuid4())
    token = auth.internal.set(True)
    paid = auth.prepaid.set(True)
    try:
        async with db_manager.engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE demo_identity SET thread_id=:thread, submissions=1 WHERE identity=:id"
                ),
                {"thread": thread_id, "id": user.identity},
            )
        async with _get_session_maker()() as session:
            ttl = {
                "strategy": "delete",
                "default_ttl": (expiry - dt.datetime.now(dt.UTC)).total_seconds() / 60,
            }
            await create_thread(
                ThreadCreate(thread_id=thread_id, ttl=ttl), user=user, session=session
            )
        async with _get_session_maker()() as session:
            run = await create_run(
                thread_id,
                RunCreate(**contract.run_request(text=body.text)),
                user=user,
                session=session,
            )
        return {
            "thread_id": thread_id,
            "run_id": run.run_id,
            "expires_at": expiry.isoformat(),
            "cookie": contract.sign_identity(user.identity, int(expiry.timestamp())),
        }
    finally:
        auth.prepaid.reset(paid)
        auth.internal.reset(token)


@app.delete("/demo/chat")
async def delete_chat(user: Annotated[User, Depends(require_auth)]):
    if not await cleanup.erase(user.identity):
        raise HTTPException(409, "deletion_pending")
    return {"deleted": True}


@app.post("/demo/retry")
async def retry(user: Annotated[User, Depends(require_auth)]):
    row = await storage.identity_row(user.identity)
    if not row:
        raise HTTPException(404, "chat_not_found")
    await auth.owned(user.identity, row["thread_id"])
    snapshot = await auth.snapshot_for(row["thread_id"], user)
    if not snapshot.config:
        raise HTTPException(409, "no_retry")
    checkpoint = {"checkpoint_id": snapshot.config["configurable"]["checkpoint_id"]}
    token = auth.internal.set(True)
    try:
        async with _get_session_maker()() as session:
            return await create_run(
                row["thread_id"],
                RunCreate(**contract.run_request(checkpoint=checkpoint)),
                user=user,
                session=session,
            )
    finally:
        auth.internal.reset(token)


@app.get("/demo/session")
async def session_info(user: Annotated[User, Depends(require_auth)]):
    row = await storage.identity_row(user.identity)
    if not row or row["expires_at"] <= dt.datetime.now(dt.UTC):
        return {"thread_id": None, "chats_remaining": 0 if row else config.DEMO_IDENTITY_CHATS}
    thread_id = None if row["deleting"] else row["thread_id"]
    latest = await auth.latest_run(thread_id) if thread_id else None
    done = (
        contract.completed(latest.status, await auth.snapshot_for(thread_id, user))
        if latest
        else False
    )
    return {
        "thread_id": thread_id,
        "complete": done,
        "status": latest.status if latest else None,
        "expires_at": row["expires_at"].isoformat(),
        "chats_remaining": config.DEMO_IDENTITY_CHATS - row["chats"],
        "submissions_remaining": config.DEMO_SUBMISSIONS - row["submissions"],
        "deleting": row["deleting"],
    }


@app.get("/demo/limits")
async def limits():
    """Server-side page bootstrap, before an identity cookie exists."""
    now = dt.datetime.now(ZoneInfo("Europe/Berlin"))
    reset = dt.datetime.combine(now.date() + dt.timedelta(days=1), dt.time(), tzinfo=now.tzinfo)
    return {
        "daily_chats": config.DEMO_DAILY_CHATS,
        "identity_chats": config.DEMO_IDENTITY_CHATS,
        "lifetime_days": config.DEMO_LIFETIME_DAYS,
        "submissions": config.DEMO_SUBMISSIONS,
        "message_chars": config.DEMO_MESSAGE_CHARS,
        "daily_reset": reset.isoformat(),
    }
