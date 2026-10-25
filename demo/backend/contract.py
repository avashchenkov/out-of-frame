"""Small, explicit contracts of the backend: the signed identity, message checks and the run
requests built on the server."""

import hashlib
import hmac
from uuid import UUID

from fastapi import HTTPException

from demo.backend import config


def secret() -> bytes:
    value = config.DEMO_PROXY_SECRET
    if len(value) < 32:
        raise RuntimeError("OUT_OF_FRAME_DEMO_PROXY_SECRET must contain at least 32 characters")
    return value.encode()


def sign_identity(identity: str, expires: int) -> str:
    UUID(identity)
    payload = f"{identity}.{expires}"
    signature = hmac.new(secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def validate_text(text):
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(422, "message_required")
    if len(text) > config.DEMO_MESSAGE_CHARS:
        raise HTTPException(422, "message_too_long")
    return text


def run_request(*, text=None, resume=False, checkpoint=None) -> dict:
    """Construct requests on the server. Never merge a browser-supplied run body."""
    body = {
        "assistant_id": "agent",
        "multitask_strategy": "reject",
        "on_disconnect": "continue",
        "durability": "sync",
        "stream_mode": ["values", "updates"],
        "stream_subgraphs": False,
    }
    if checkpoint is not None:
        body["checkpoint"] = checkpoint
    elif resume:
        body["command"] = {"resume": validate_text(text)}
    else:
        body["input"] = {"messages": [{"type": "human", "content": validate_text(text)}]}
    return body


def completed(run_status: str, snapshot) -> bool:
    return (
        run_status == "success"
        and not snapshot.next
        and not snapshot.interrupts
        and any(
            (m.get("id") if isinstance(m, dict) else m.id) == "final-report"
            for m in snapshot.values.get("messages", [])
        )
    )
