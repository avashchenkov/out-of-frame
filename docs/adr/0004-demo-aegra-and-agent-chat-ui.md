# 4. Demo: Aegra and Agent Chat UI

Status: accepted, 2026-10-22

Access rules, public scope and deployment updated on 2026-10-23.

This decision covers [demo steps 5 to 8](../roadmap.md#after-the-mvp-the-demo).
The [demo architecture](../demo-architecture.md) defines access, limits and retention;
the [launch checklist](../demo-launch-checklist.md) covers notices and deployment requirements.

## Context

The demo offers author-prepared recorded examples and a private chat without sign-up.
It needs a server that runs the existing LangGraph graph, saves progress between messages
and recovers interrupted work, plus a page for questions and reports. Public usage is bounded
by admission limits and separate provider budgets. Only the page is open to the internet.

## Decision

- **Backend: [Aegra](https://github.com/aegra/aegra),** a self-hosted LangGraph server under the
  Apache 2.0 licence. It serves the Agent Protocol, persists conversations in PostgreSQL
  and supports the LangGraph SDK.
- **Frontend: LangChain's [Agent Chat UI](https://github.com/langchain-ai/agent-chat-ui),** a
  Next.js chat page under the MIT licence, cloned into `demo/` and adapted for this graph.
- **Deployment:** one VPS with Docker Compose: Next.js, Aegra, PostgreSQL and Redis.
  Redis enables Aegra's built-in worker recovery and holds temporary stream events.
  PostgreSQL keeps server records and checkpoints.

Next.js manages the cookie, serves examples, constructs allowed run requests and filters
browser responses. Aegra's demo handlers enforce
ownership and admission. Visitor conversations and reports remain private.

## Alternatives

- **LangSmith Deployment:** the same API, but self-hosting it is part of the Enterprise plan,
  and its cloud is a paid service.
- **An API of our own,** such as FastAPI around the graph: LangGraph would still pause and
  stream, but we would write the HTTP routes, the storage of conversations and the auth, and
  no ready chat page would speak it.
- **Chainlit for the page:** Python, flexible, and known to the author. Its repository was
  archived on 2026-10-15, so a page open to anyone would get no more security fixes. Its chat
  history also needs signing in.
- **A custom page,** such as FastAPI with templates: no fork and no TypeScript, but we would
  write and secure the chat, the streaming and the conversation history ourselves.

## Consequences

- Agent Chat UI needs LangChain messages in `messages`. Append the finished report once,
  keep `report` for the CLI and judges, and preserve loading of old `{role, text}` runs.
- Questions use `interrupt()`; answers resume a saved checkpoint. Stream progress and saved
  service-failure notices alongside the report. Reconnect to a run after browser disconnection.
- Each visitor has a separate pseudonymous identity. Set its cookie on the first admitted
  message, never on refused admission. Keep only the current conversation and provide owner
  deletion/replacement. The start notice explains that clearing cookies loses access while
  server records remain subject to the original expiry.
- The proxy must filter streams and state responses: the standard UI can receive the whole
  graph state. Expose only the conversation, final report and required status/progress data.
- Recorded examples are frontend files, not live database threads. No public visitor-report
  API, report-copy table or publication flow is needed.
- Keep PostgreSQL: Aegra requires it beyond the graph's checkpoints. Redis runs without disk
  persistence; recovery uses PostgreSQL. Coordinate cancellation and cleanup so workers
  cannot recreate deleted data.
- The page is a TypeScript fork in the repository; merge upstream updates by hand.
