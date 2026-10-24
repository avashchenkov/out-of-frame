"""Small, explicit contracts shared by admission and the future Web UI proxy."""

import hashlib
import hmac
import time
from uuid import UUID, uuid4

from fastapi import HTTPException

from demo.backend import config
from out_of_frame.cli import PROGRESS

COOKIE_NAME = "oof_identity"
COOKIE_OPTIONS = {"httponly": True, "secure": True, "samesite": "lax", "path": "/"}


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


def read_identity(token: str) -> tuple[str, int]:
    try:
        identity, raw_expiry, _ = token.split(".")
        expiry = int(raw_expiry)
        if not hmac.compare_digest(sign_identity(identity, expiry), token):
            raise ValueError
        if expiry <= time.time():
            raise ValueError
        return identity, expiry
    except ValueError, TypeError:
        raise HTTPException(401, "invalid_identity") from None


def candidate_identity() -> str:
    """Proxy-only candidate. Set a cookie only after admission, with the returned expiry."""
    return str(uuid4())


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


def visible_values(values: dict) -> dict:
    """No internal source, draft, message metadata, tools or model output crosses this boundary."""
    messages = []
    for message in values.get("messages", []):
        if not isinstance(message, dict):
            message = message.model_dump()
        kind, content = message.get("type"), message.get("content")
        if kind not in ("human", "ai") or not isinstance(content, str):
            continue
        messages.append({"type": kind, "content": content, "id": message.get("id")})
    failures = [
        f for f in values.get("failures", []) if f in ("map", "plans", "transit", "web search")
    ]
    return {"messages": messages, "failures": failures}


def visible_event(event: str, data) -> dict | None:
    """An allowlist for SSE, including replay. Unknown events and fields are discarded."""
    if event == "values" and isinstance(data, dict):
        return visible_values(data)
    if event == "updates" and isinstance(data, dict):
        return {node: {"progress": node} for node in data if node in PROGRESS}
    if event == "metadata" and isinstance(data, dict):
        return {key: data[key] for key in ("run_id", "thread_id") if key in data}
    if event == "error":
        return {"error": "run_failed"}
    return None


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


def visible_read(kind: str, data: dict) -> dict:
    """Projection for every JSON read the proxy may expose. History stays disabled."""
    if kind == "state":
        result = {"values": visible_values(data.get("values", {}))}
        result["next"] = [node for node in data.get("next", []) if node == "wait_for_answer"]
        result["interrupts"] = [
            {"id": item["id"], "value": item["value"]}
            for item in data.get("interrupts", [])
            if isinstance(item, dict) and isinstance(item.get("value"), str) and "id" in item
        ]
        return result
    if kind in ("thread", "run"):
        return {key: data[key] for key in ("thread_id", "run_id", "status") if key in data}
    raise ValueError("read route is not exposed")
