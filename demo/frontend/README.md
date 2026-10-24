# Web UI

The Next.js interface lives here, separate from the Python agent and demo backend.
It restores the browser's private conversation and report, with live input disabled.
Queued and running chats refresh automatically. Returning to the page or selecting
Reload chat reads the current server state without starting a run. Source-failure notices
and remaining submissions are restored too. Chat content stays in memory, without browser
storage. The page clears it when access expires or a read fails.
The session includes the latest run ID. The page attaches to its filtered SSE stream using
the browser's EventSource, with native cursor-based reconnection. Events show fixed progress
notices and trigger a current-state read, so old replay events cannot replace newer messages.
Periodic reads also track queued runs and recover state when replay is no longer available.

Use Node.js 24 and npm. From this directory:

```sh
npm ci
npm run dev
```

Open <http://127.0.0.1:3000>. To check a change:

```sh
npm run build
npm run typecheck
npm run typecheck:tests
npm run lint
npm test
npm run format:check
```

## Private API

Configure the server with the values in [.env.example](.env.example).
`OUT_OF_FRAME_DEMO_ORIGIN` is the public website origin; it is not taken from forwarded
headers. `OUT_OF_FRAME_DEMO_BACKEND_URL` is Aegra's private address. The proxy secret must
match the backend and contain at least 32 characters.

The `/api/demo/` proxy allows `GET limits`, `GET session`, `GET threads/{id}`,
`GET threads/{id}/state` and `GET threads/{id}/runs/{runId}`. Private reads require the
backend-compatible signed identity cookie; Aegra checks chat ownership. A cookie-free
session read returns an empty session. Reads never issue or renew cookies.

`GET threads/{id}/runs/{runId}/stream` attaches to an existing run. Send its last received
`Last-Event-ID` to replay missed events. The cursor must belong to that run. This uses Aegra's
existing stream and replay buffer; attaching never submits another run.

The proxy constructs backend credentials, checks request origins and filters JSON and SSE.
Streams expose visible messages, fixed progress names, failures, IDs and terminal status.
Comments become fixed keepalives. Disconnect closes only the stream connection; it does
not cancel the run. Cookie expiry closes the connection too. Responses are private and
non-cacheable; upstream headers and raw errors stay private. History routes remain disabled.

The proxy also supports these mutations. Send the configured website `Origin` and
`X-Demo-CSRF: 1`; POST bodies use `Content-Type: application/json`:

| Route                    | Body                             | Behaviour                                                            |
| ------------------------ | -------------------------------- | -------------------------------------------------------------------- |
| `POST chat`              | `{"text":"...","replace":false}` | Start a private chat; `replace: true` deletes the current chat first |
| `POST threads/{id}/runs` | `{"text":"..."}`                 | Answer a saved question                                              |
| `POST retry`             | `{}`                             | Retry from the checkpoint selected by the backend                    |
| `DELETE chat`            | Empty                            | Delete the current chat, retaining quota records                     |

The first admitted chat sets the signed HttpOnly, Secure, SameSite=Lax cookie with the
backend's fixed expiry. Later chats, answers, retries and deletion do not renew or remove it.
Refused admission sets no cookie. Run settings are constructed by the server, and unknown
input fields are rejected. The backend enforces ownership and quotas. Errors expose fixed
codes, including the relevant quota or deletion refusal.

`OUT_OF_FRAME_DEMO_LIVE_ENABLED` defaults to `false`: submissions and retries return
`live_unavailable` until enabled after the launch checklist. Private reads and deletion
remain available. The chat page's input is still disabled.

Frontend boundary tests live in `tests/demo/frontend/` and use Node's built-in test runner
with stubbed backend responses. They need no API keys, database or Docker.

## Upstream

The thread layout, scroll behaviour and Markdown renderer are adapted from
[Agent Chat UI](https://github.com/langchain-ai/agent-chat-ui/tree/7a503412aeeb4534a24b04bd97b618ee3871821e),
commit `7a503412aeeb4534a24b04bd97b618ee3871821e`.
Its MIT licence is retained in [LICENSE](LICENSE).
Upstream source files: `src/components/thread/index.tsx`,
`src/components/thread/messages/human.tsx` and `src/components/thread/markdown-text.tsx`.
This version keeps text messages, automatic scrolling and GitHub-flavoured Markdown.
It has no server selection, thread history, branching, message editing or file uploads.
