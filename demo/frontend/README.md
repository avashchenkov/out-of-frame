# Web UI

The Next.js interface lives here, separate from the Python agent and demo backend.
It currently shows the chat layout with live input disabled.

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

## Private API reads

Configure the server with the values in [.env.example](.env.example).
`OUT_OF_FRAME_DEMO_ORIGIN` is the public website origin; it is not taken from forwarded
headers. `OUT_OF_FRAME_DEMO_BACKEND_URL` is Aegra's private address. The proxy secret must
match the backend and contain at least 32 characters.

The `/api/demo/` proxy allows `GET limits`, `GET session`, `GET threads/{id}`,
`GET threads/{id}/state` and `GET threads/{id}/runs/{runId}`. Private reads require the
backend-compatible signed identity cookie; Aegra checks chat ownership. A cookie-free
session read returns an empty session. Reads never issue or renew cookies.

The proxy constructs backend credentials, checks request origins and filters JSON responses.
It returns private, non-cacheable responses and fixed errors. Mutation, history and streaming
routes are disabled. Live input remains disabled.

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
