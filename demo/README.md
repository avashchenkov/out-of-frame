# Demo backend

The existing agent served by Aegra v0.10.8. Demo server code and settings live in
`demo/backend/`, outside the installed agent package. Demo tests live in `tests/demo/`.
PostgreSQL holds conversations, checkpoints and admission counters. Redis holds queued runs
and temporary stream events. This backend is private and must not be exposed to browsers
directly.

## Run

### Docker Compose

From `demo/`, copy `.env.example` to `.env` and fill in the database password, proxy secret
and API keys. Use a URL-safe database password, such as the output of `openssl rand -hex 32`.
The environment file stays on the host; it is never a build input. Agent overrides from
the root example can be added to this file. Compose sets database URLs with the private
service names `postgres` and `redis`.

Build the image, start the databases, then prepare their schema separately:

```sh
docker compose --env-file .env build backend
docker compose --env-file .env up -d --wait postgres redis
docker compose --env-file .env run --rm --no-deps backend aegra db upgrade
docker compose --env-file .env exec -T postgres \
  psql -U out_of_frame -d out_of_frame --set ON_ERROR_STOP=1 --single-transaction < db/schema.sql
docker compose --env-file .env up -d --wait backend
```

Do the preparation before the first start and after an Aegra upgrade, with the backend
stopped. The SQL is safe to apply again. There is no custom setup command in the server.
Aegra's standard CLI and bundled migrations remain upstream dependencies; our deployment
SQL stays outside the image.

The runtime image installs the agent as a package with locked dependencies, without an
editable source checkout. It runs as a non-root user. Project tests, evals, fixtures, uv,
Ruff, pytest, secrets and deployment SQL are excluded. The root `.dockerignore` allows only
backend build inputs; a separate build stage keeps source and build tools out of the final image.

The same Compose file runs the [Web UI](frontend/README.md) and Caddy. Only Caddy publishes
host ports, 80 and 443; it gets an HTTPS certificate for `OUT_OF_FRAME_DEMO_DOMAIN` and
forwards to the Web UI. Only containers in the Compose network can reach Aegra on port 2026.
The Web UI receives only its own settings from the environment file, not the model or source
keys. PostgreSQL and Caddy's certificates use persistent named volumes; Redis uses memory
without RDB/AOF. Containers restart automatically after a failure or a host reboot.

Use `docker compose --env-file .env down` to stop the services and keep PostgreSQL data.
For a full data reset, stop the backend first, then run
`docker compose --env-file .env down --volumes`; this deletes all conversations and quotas.
Do not use the disposable [test Compose](testing.md) for stored conversations.

### Deployment on a server

The server only runs the images; it never builds them. The images are built on a
development machine and copied over SSH, so the server needs no source code or build tools.

[`deploy/bootstrap-host.sh`](deploy/bootstrap-host.sh) prepares a Debian or Ubuntu host once.
Run it as root after adding an SSH key. It creates a `deploy` user with the same keys, turns
off password and root login, allows only SSH, HTTP and HTTPS through the firewall, enables
automatic security updates, installs Docker unless it is already there and adds swap unless
swap exists. Container logs go to the system journal, which keeps them for up to
24 hours.

Point the domain's DNS record to the server. Create `~/out-of-frame/demo/.env` on the server
from [`.env.example`](.env.example). Then, for the first start and each update, run from a
clean checkout on the development machine:

```sh
demo/deploy/release.sh deploy@server
```

[`release.sh`](deploy/release.sh) builds both images for `linux/amd64`, copies them and the
deployment files (Compose file, Caddyfile, database SQL and
[`deploy.sh`](deploy/deploy.sh)) to the server, and runs `deploy.sh` there. That script
stops the backend, applies the database steps above and starts all services. The Web UI
keeps serving the examples while the backend is stopped. Caddy's access log holds the
client IP, time, request line and status, without headers or cookies. Read it on the server
with `docker compose logs caddy` from `~/out-of-frame/demo`.

### Local UI stack with a stub agent

To try the Web UI without paid calls, run the real Web UI, Aegra, PostgreSQL and Redis with a
stub agent in place of the real one. It needs no keys and no `.env`. From the repository root:

```sh
docker compose --file demo/compose.stub.yaml up --build --wait
```

Then open <http://localhost:3000>. The stub, in [`stub/agent.py`](stub/agent.py), has the
real graph's steps and the same ownership checks, so the page shows the same progress,
question, retry and report. A run takes about 40 seconds; set
`OUT_OF_FRAME_DEMO_STUB_DELAY=0.3` for faster runs, or `0` for instant ones. The report is a
full recorded example under your address: Teutonenstraße 10, with journeys, if you travel
somewhere, or Corinthstraße 60 if not. The address of a recorded example gets its own report.

- It asks one question at most, and any answer leads on to the report. Without any number in
  the message, it asks for the address; without a word about trips, such as "nowhere" or
  "work", it asks where you travel.
- "fail" in a message adds the transit and web search failure notices.
- "crash" in a message stops the first run with an error, so that Retry can be tried.

The stub has its own Aegra config, [`stub/aegra.json`](stub/aegra.json); Compose mounts
`stub/` into the backend container and points `AEGRA_CONFIG` to it. The runtime image, its
config and `backend/` never include or name the stub.

A visitor gets 20 chats, set with `OUT_OF_FRAME_DEMO_IDENTITY_CHATS`. Chats stay in a Docker
volume between restarts. Stop the stack with
`docker compose --file demo/compose.stub.yaml down`; add `--volumes` to delete all chats and
quotas.

### Local Python process

Install with `uv sync --locked --extra demo`. Provide PostgreSQL and Redis, without Redis
RDB/AOF persistence. Configure the agent keys from the root `.env.example` and the service
settings from [`.env.example`](.env.example) in the service environment. Set `DATABASE_URL`
and `REDIS_URL` to those services explicitly; Compose supplies them only inside containers.
No judge keys or eval settings are needed. No live run is part of startup.

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

The Web UI server and the backend share `OUT_OF_FRAME_DEMO_PROXY_SECRET`; the browser never
sees it. The Web UI verifies the signed identity cookie and sends `x-demo-key`, `x-demo-identity` (the verified random UUID), and
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

Native Aegra responses contain internal state and never reach the browser. The Web UI proxy
filters every browser response and replay through allowlists in
[`visible-response.ts`](frontend/src/server/visible-response.ts). SSE keeps only top-level
values, fixed progress and required IDs; message metadata, sources, draft reports and raw
errors are excluded. JSON responses keep only visible messages, failure codes and the status
needed to resume. Unknown routes and events are discarded.

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
