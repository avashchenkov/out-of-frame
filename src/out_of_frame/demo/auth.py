"""Only the Web UI proxy can assert a browser identity; Aegra still enforces ownership."""

import datetime as dt
import hmac
from contextvars import ContextVar
from uuid import UUID

from aegra_api.core.database import db_manager
from aegra_api.core.orm import Run, _get_session_maker
from aegra_api.services.langgraph_service import get_langgraph_service
from fastapi import HTTPException
from langgraph_sdk import Auth
from sqlalchemy import select, text

from out_of_frame import config
from out_of_frame.demo import contract, storage

internal = ContextVar("demo_internal", default=False)
prepaid = ContextVar("demo_prepaid", default=False)
auth = Auth()


@auth.authenticate
async def authenticate(headers: dict) -> dict:
    headers = {k.lower(): v for k, v in headers.items()}
    if not hmac.compare_digest(headers.get("x-demo-key", "").encode(), contract.secret()):
        raise HTTPException(401, "proxy_required")
    identity = headers.get("x-demo-identity", "")
    try:
        UUID(identity)
    except ValueError:
        raise HTTPException(401, "identity_required") from None
    return {"identity": identity, "is_authenticated": True}


@auth.on
async def deny(ctx, value):
    return False


@auth.on.assistants.read
async def assistant(ctx, value):
    return str(value.get("assistant_id")) == "agent"


async def owned(identity, thread_id):
    row = await storage.identity_row(identity)
    if (
        not row
        or row["thread_id"] != thread_id
        or row["deleting"]
        or row["expires_at"] <= dt.datetime.now(dt.UTC)
    ):
        raise HTTPException(404, "chat_not_found")
    return row


@auth.on.threads.read
async def read(ctx, value):
    await owned(ctx.user.identity, value.get("thread_id"))
    return {"metadata": {"owner": ctx.user.identity}}


@auth.on.threads.create
async def create(ctx, value):
    return internal.get()


@auth.on.threads.delete
async def delete(ctx, value):
    return internal.get()


async def snapshot_for(thread_id, user):
    async with get_langgraph_service().get_graph(
        "agent", access_context="threads.read", user=user
    ) as graph:
        return await graph.aget_state({"configurable": {"thread_id": thread_id}})


async def latest_run(thread_id):
    async with _get_session_maker()() as session:
        return await session.scalar(
            select(Run).where(Run.thread_id == thread_id).order_by(Run.created_at.desc()).limit(1)
        )


def validate_run(value):
    fixed = {
        "assistant_id": "agent",
        "multitask_strategy": "reject",
        "on_disconnect": "continue",
        "durability": "sync",
        "stream_mode": ["values", "updates"],
        "stream_subgraphs": False,
    }
    if any(value.get(k) != v for k, v in fixed.items()):
        raise HTTPException(422, "execution_override")
    for key in (
        "config",
        "context",
        "metadata",
        "interrupt_before",
        "interrupt_after",
        "checkpoint_during",
        "on_completion",
        "checkpoint_id",
    ):
        if value.get(key):
            raise HTTPException(422, "execution_override")
    if value.get("checkpoint") is not None and not internal.get():
        raise HTTPException(422, "checkpoint_override")
    initial, command = value.get("input"), value.get("command")
    if initial is not None:
        try:
            [message] = initial["messages"]
            if (
                set(initial) != {"messages"}
                or set(message) != {"type", "content"}
                or message["type"] != "human"
            ):
                raise ValueError("text_only")
        except ValueError, KeyError, TypeError:
            raise HTTPException(422, "text_only") from None
        contract.validate_text(message["content"])
    elif command is not None:
        if set(command) != {"resume"}:
            raise HTTPException(422, "resume_only")
        contract.validate_text(command["resume"])
    elif not internal.get() or not value.get("checkpoint"):
        raise HTTPException(422, "text_required")


@auth.on.threads.create_run
async def admit(ctx, value):
    validate_run(value)
    thread_id = value.get("thread_id")
    await owned(ctx.user.identity, thread_id)
    previous = await latest_run(thread_id)
    if previous:
        if previous.status in ("pending", "running"):
            raise HTTPException(409, "run_active")
        snapshot = await snapshot_for(thread_id, ctx.user)
        if contract.completed(previous.status, snapshot):
            raise HTTPException(409, "chat_complete")
        if value.get("input") is not None:
            raise HTTPException(422, "resume_required")
        if value.get("command") is not None and not snapshot.interrupts:
            raise HTTPException(409, "no_question")
        if value.get("checkpoint") is not None and (
            previous.status != "error" or not snapshot.next
        ):
            raise HTTPException(409, "no_retry")
    elif value.get("input") is None:
        raise HTTPException(422, "first_message_required")
    if not prepaid.get():
        async with db_manager.engine.begin() as conn:
            changed = await conn.execute(
                text("""
                UPDATE demo_identity SET submissions=submissions+1
                WHERE identity=:id AND submissions<:cap AND NOT deleting AND expires_at>now()
                RETURNING submissions
            """),
                {"id": ctx.user.identity, "cap": config.DEMO_SUBMISSIONS},
            )
            if changed.scalar_one_or_none() is None:
                raise HTTPException(429, "submissions_exhausted")
    return {"metadata": {"owner": ctx.user.identity}}
