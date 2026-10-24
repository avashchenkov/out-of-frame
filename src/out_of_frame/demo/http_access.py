"""Limit the private Aegra API to requests constructed by the Web UI server."""

import hmac
import re
from contextlib import AsyncExitStack
from uuid import UUID

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from out_of_frame.demo import auth, contract, storage

CUSTOM_ROUTES = {
    "/demo/chat": {"POST", "DELETE"},
    "/demo/retry": {"POST"},
    "/demo/session": {"GET"},
    "/demo/cleanup": {"POST"},
    "/demo/limits": {"GET"},
}
THREAD_READ = re.compile(r"/threads/(?P<thread_id>[^/]+)(?:/state|/runs/[^/]+(?:/join|/stream)?)?")
RUN_CREATE = re.compile(r"/threads/[^/]+/runs(?:/stream|/wait)?")
MAX_REQUEST_BYTES = 16_384


class PrivateDemoAccess:
    """Check proxy credentials, routes and ownership before Aegra handles a request.

    The Web UI server checks browser origin/CSRF and asserts that check in a header.
    Mutations hold the identity lock until response headers, without locking an entire
    event stream. Native run admission also checks ownership in the auth handlers.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in ("/health", "/ready", "/live"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        response_started = False
        try:
            if not hmac.compare_digest(headers.get("x-demo-key", "").encode(), contract.secret()):
                raise HTTPException(401, "proxy_required")
            path, method = scope["path"], scope["method"]
            thread_read = THREAD_READ.fullmatch(path) if method == "GET" else None
            run_create = method == "POST" and RUN_CREATE.fullmatch(path)
            if not (method in CUSTOM_ROUTES.get(path, ()) or thread_read or run_create):
                raise HTTPException(403, "route_disabled")
            identity = headers.get("x-demo-identity", "")
            if path not in ("/demo/cleanup", "/demo/limits"):
                try:
                    UUID(identity)
                except ValueError:
                    raise HTTPException(401, "identity_required") from None
            if method in ("POST", "DELETE") and headers.get("x-demo-csrf") != "1":
                raise HTTPException(403, "csrf_required")
            if thread_read:
                # Aegra does not invoke the threads.read auth hook on every native GET.
                # Hide expired/deleting chats even while checkpoints or replay buffers remain.
                await auth.owned(identity, thread_read["thread_id"])

            body = bytearray()
            while True:
                event = await receive()
                if event["type"] == "http.disconnect":
                    return
                body.extend(event.get("body", b""))
                if len(body) > MAX_REQUEST_BYTES:
                    raise HTTPException(413, "request_too_large")
                if not event.get("more_body"):
                    break
            delivered = False

            async def replay_body():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body)}
                return await receive()

            async with AsyncExitStack() as mutation_lock:
                if method in ("POST", "DELETE") and path != "/demo/cleanup":
                    await mutation_lock.enter_async_context(storage.locked(identity))

                async def private_response(event):
                    nonlocal response_started
                    if event["type"] == "http.response.start":
                        response_started = True
                        event = event | {
                            "headers": [
                                (key, value)
                                for key, value in event.get("headers", [])
                                if key.lower() != b"cache-control"
                            ]
                            + [(b"cache-control", b"private, no-store")]
                        }
                        await mutation_lock.aclose()
                    await send(event)

                await self.app(scope, replay_body, private_response)
        except HTTPException as error:
            if response_started:
                raise
            response = JSONResponse(
                {"error": error.detail},
                status_code=error.status_code,
                headers={"Cache-Control": "private, no-store"},
            )
            await response(scope, receive, send)
