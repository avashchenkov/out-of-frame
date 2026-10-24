# Demo backend

The existing agent served by Aegra v0.10.8. Demo server code and settings live in
`demo/backend/`, outside the installed agent package. Demo tests live in `tests/demo/`.
PostgreSQL holds conversations, checkpoints and admission counters. Redis holds queued runs
and temporary stream events. This backend is private and must not be exposed to browsers
directly.

## Run

Install with `uv sync --locked --extra demo`. Provide PostgreSQL and Redis, without Redis
RDB/AOF persistence. Configure the agent keys from the root `.env.example` and the service
settings from [`.env.example`](.env.example) in the service environment. No judge keys or eval
settings are needed. No live run is part of startup.

Apply the [database deployment steps](db/README.md) before starting the service. Demo DDL
stays outside the runtime package; the server does not create its admission tables.

From the repository root, run:

```sh
AEGRA_CONFIG=demo/aegra.json \
uv run --extra demo python -m uvicorn aegra_api.main:app --host 127.0.0.1 --port 2026
```

Use one Aegra process with `WORKER_COUNT=1` and `N_JOBS_PER_WORKER=1`. The service refuses
a second process on the same database. This keeps cancellation and admission in one process.
The database lock guards startup only. Stop Aegra before restarting PostgreSQL; after an
unexpected database connection loss, restart Aegra before starting another instance.
Replicas and rolling updates are not supported.
External tracing and the independent TTL sweeper are refused. Cleanup uses Aegra's native
per-thread TTL pruning after stopping work and clearing Redis.

One run executes at a time across all visitors. Other admitted runs stay `pending` in Aegra's
native queue and start automatically when the current run finishes or pauses for user input.
Waiting does not consume extra quota. The Web UI must show the queued notice from the
[architecture](../docs/demo-architecture.md#demo-limits), reconnect without resubmitting and
keep deletion available. Worker concurrency does not replace Anthropic's rate limits.

## Private proxy contract

Only the Web UI server knows `OUT_OF_FRAME_DEMO_PROXY_SECRET`. It verifies the signed identity
cookie and sends `x-demo-key`, `x-demo-identity` (the verified random UUID), and
`x-demo-csrf: 1` after its own origin/CSRF check. Never forward browser-supplied identity or
execution headers. A first request uses a fresh candidate UUID, without setting a cookie yet.

- `POST /demo/chat` with `{ "text": "...", "replace": false }` admits the first message,
  creates a native thread and starts its first run. `replace: true` deletes the current chat
  first. The response includes thread/run IDs, the fixed expiry and a signed cookie value.
  Only a successful admission sets the HttpOnly/Secure/SameSite=Lax cookie. The proxy sets
  its absolute expiry from this response and never exposes the signed value in browser JSON.
- Subsequent answers use native `/threads/{id}/runs` or `/runs/stream` with the fixed request
  built by `contract.run_request(resume=True, text=...)`. No arbitrary execution config,
  checkpoint, state edits, history, branching or stateless routes are enabled.
- `POST /demo/retry` selects the latest checkpoint after an execution error. It consumes a
  submission. Worker crash recovery reuses the original admitted run and consumes none.
- `GET /demo/limits` supplies configured limits and the next Berlin midnight to the page
  before a cookie exists.
- `GET /demo/session` returns the current thread, remaining quotas, expiry and completion.
  Native state/run reads and reconnect streams remain available to the private proxy.
- `DELETE /demo/chat` removes content without refunding quota. A `deletion_pending` response
  means work has not stopped yet; content is hidden and periodic cleanup retries.

The proxy must apply the allowlists in `contract.visible_read` and `contract.visible_event`
to every browser response and replay. Native Aegra responses contain internal state and are
not browser responses. SSE keeps only top-level values, fixed progress and required IDs;
message metadata, sources, draft reports and raw errors are excluded. JSON projections keep
only visible messages, failure codes and the status needed to resume. Unknown routes/events
are discarded. Implement and verify these projections in the Web UI proxy in roadmap step 7.

Limits and retention are defined in [the demo architecture](../docs/demo-architecture.md).
A quota is reserved before execution, including failed or abandoned attempts. New chat does
not renew expiry. A replacement that times out during deletion still consumes its admitted
slot; it does not create another thread while old work can write.

## Cleanup and verification

Expired content becomes inaccessible immediately. Automatic cleanup runs at startup and
every configured interval, after worker tasks and synchronous nodes stop. Pending deletions
keep only the identifiers needed to retry a partial purge. Visitors delete their current
chat through `DELETE /demo/chat`.

For a manual deletion request or demo closure, stop the backend and discard all demo
PostgreSQL and Redis data. No separate administration command or API is provided.

Offline checks without database services:

```sh
uv run --no-env-file --offline --no-sync pytest tests/demo
```

Integration checks start real Aegra processes with fake model/source calls. Use the
[Compose test runner](testing.md) for disposable PostgreSQL and Redis. It supplies temporary
connection URLs and removes its infrastructure after the checks. Tests clear their demo/thread
tables and never read `.env` or call external APIs.

These checks cover restart/resume, worker crash recovery, disconnects, quotas and concurrent
tabs, queue processing, ownership, fixed execution parameters, manual retry, replacement,
expiry, deletion while synchronous work is still running, and PostgreSQL/Redis cleanup.
