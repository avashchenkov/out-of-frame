"""Private HTTP access rules, including reads before physical deletion completes."""

import asyncio
import datetime as dt
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from demo.backend import config, storage
from demo.backend.http_access import MAX_REQUEST_BYTES, PrivateDemoAccess

IDENTITY = str(uuid4())
HEADERS = {"x-demo-key": "a" * 32, "x-demo-identity": IDENTITY, "x-demo-csrf": "1"}
PRIVATE_REPORT = b"PRIVATE_REPORT_MUST_NOT_LEAK"
READ_PATHS = [
    "/threads/current-chat",
    "/threads/current-chat/state",
    "/threads/current-chat/runs/run-id",
    "/threads/current-chat/runs/run-id/join",
    "/threads/current-chat/runs/run-id/stream",
]


async def request(app, path, method="GET", headers=None, chunks=None):
    headers = HEADERS if headers is None else headers
    chunks = [b""] if chunks is None else chunks
    incoming = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]
    outgoing = []

    async def receive():
        return incoming.pop(0) if incoming else {"type": "http.disconnect"}

    async def send(event):
        outgoing.append(event)

    await app(
        {
            "type": "http",
            "path": path,
            "method": method,
            "headers": [(key.encode(), value.encode()) for key, value in headers.items()],
        },
        receive,
        send,
    )
    return outgoing


@pytest.fixture
def boundary(monkeypatch):
    monkeypatch.setattr(config, "DEMO_PROXY_SECRET", "a" * 32)
    monkeypatch.setattr(
        storage,
        "identity_row",
        AsyncMock(
            return_value={
                "thread_id": "current-chat",
                "deleting": False,
                "expires_at": dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
            }
        ),
    )

    async def respond(scope, receive, send):
        await receive()
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"cache-control", b"public, max-age=3600")],
            }
        )
        await send({"type": "http.response.body", "body": PRIVATE_REPORT})

    downstream = AsyncMock(side_effect=respond)
    return PrivateDemoAccess(downstream), downstream


@pytest.mark.parametrize("path", READ_PATHS)
@pytest.mark.parametrize("invalid", ["missing", "expired", "deleting", "other_chat"])
def test_unavailable_chat_never_reaches_state_or_replay_handlers(
    boundary, monkeypatch, path, invalid
):
    row = {
        "thread_id": "other-chat" if invalid == "other_chat" else "current-chat",
        "deleting": invalid == "deleting",
        "expires_at": dt.datetime.now(dt.UTC)
        + dt.timedelta(days=-1 if invalid == "expired" else 1),
    }
    monkeypatch.setattr(
        storage, "identity_row", AsyncMock(return_value=None if invalid == "missing" else row)
    )
    app, downstream = boundary
    events = asyncio.run(request(app, path))
    assert events[0]["status"] == 404
    assert PRIVATE_REPORT not in b"".join(event.get("body", b"") for event in events)
    downstream.assert_not_called()


@pytest.mark.parametrize("path", READ_PATHS)
def test_owner_can_read_and_responses_override_public_caching(boundary, path):
    app, downstream = boundary
    events = asyncio.run(request(app, path))
    assert events[0]["status"] == 200
    assert events[0]["headers"] == [(b"cache-control", b"private, no-store")]
    assert events[1]["body"] == PRIVATE_REPORT
    downstream.assert_awaited_once()
    storage.identity_row.assert_awaited_once_with(IDENTITY)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        HEADERS | {"x-demo-key": "wrong"},
        HEADERS | {"x-demo-identity": "invalid"},
    ],
)
def test_missing_proxy_credentials_or_identity_are_rejected(boundary, headers):
    app, downstream = boundary
    assert asyncio.run(request(app, "/demo/session", headers=headers))[0]["status"] == 401
    downstream.assert_not_called()


@pytest.mark.parametrize(
    "path,method",
    [
        ("/threads", "POST"),
        ("/runs", "POST"),
        ("/threads/current-chat/state", "POST"),
        ("/threads/current-chat/history", "GET"),
        ("/demo/cleanup", "GET"),
        ("/demo/limits", "POST"),
        ("/demo/session", "DELETE"),
    ],
)
def test_only_supported_routes_and_methods_are_allowed(boundary, path, method):
    app, downstream = boundary
    assert asyncio.run(request(app, path, method))[0]["status"] == 403
    downstream.assert_not_called()


@pytest.mark.parametrize(
    "path,method",
    [
        ("/demo/chat", "POST"),
        ("/demo/chat", "DELETE"),
        ("/threads/current-chat/runs", "POST"),
    ],
)
def test_mutations_require_the_proxy_csrf_assertion(boundary, path, method):
    app, downstream = boundary
    headers = {key: value for key, value in HEADERS.items() if key != "x-demo-csrf"}
    assert asyncio.run(request(app, path, method, headers=headers))[0]["status"] == 403
    downstream.assert_not_called()


def test_chunked_body_limit_applies_before_delegation(boundary):
    app, downstream = boundary
    events = asyncio.run(
        request(app, "/demo/chat", "POST", chunks=[b"x" * MAX_REQUEST_BYTES, b"x"])
    )
    assert events[0]["status"] == 413
    assert (b"cache-control", b"private, no-store") in events[0]["headers"]
    downstream.assert_not_called()


@pytest.mark.parametrize(
    "path,method,headers",
    [
        ("/demo/limits", "GET", {"x-demo-key": "a" * 32}),
        ("/demo/cleanup", "POST", {"x-demo-key": "a" * 32, "x-demo-csrf": "1"}),
        ("/ready", "GET", {}),
    ],
)
def test_bootstrap_operator_cleanup_and_health_need_no_identity(boundary, path, method, headers):
    app, downstream = boundary
    assert asyncio.run(request(app, path, method, headers=headers))[0]["status"] == 200
    downstream.assert_awaited_once()


def test_mutations_share_a_lock_but_do_not_lock_the_entire_event_stream(monkeypatch):
    async def scenario():
        monkeypatch.setattr(config, "DEMO_PROXY_SECRET", "a" * 32)
        first_entered, release_headers, finish_stream = (asyncio.Event() for _ in range(3))
        calls, received_bodies = 0, []

        async def respond(scope, receive, send):
            nonlocal calls
            calls += 1
            first = calls == 1
            received_bodies.append((await receive())["body"])
            if first:
                first_entered.set()
                await release_headers.wait()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            if first:
                await finish_stream.wait()
            await send({"type": "http.response.body", "body": b"done"})

        app = PrivateDemoAccess(respond)
        first = asyncio.create_task(
            request(app, "/demo/chat", "POST", chunks=[b"first", b" message"])
        )
        await first_entered.wait()
        second = asyncio.create_task(request(app, "/demo/chat", "POST", chunks=[b"second"]))
        try:
            await asyncio.sleep(0)
            assert calls == 1
            release_headers.set()
            assert (await asyncio.wait_for(second, 1))[0]["status"] == 200
            assert not first.done()
            assert received_bodies == [b"first message", b"second"]
        finally:
            release_headers.set()
            finish_stream.set()
            await asyncio.gather(first, second, return_exceptions=True)

    asyncio.run(scenario())
