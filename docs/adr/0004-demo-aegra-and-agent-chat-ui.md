# 4. Demo: Aegra and Agent Chat UI

Status: accepted, 2026-10-22

This decision is about the public demo ([roadmap](../roadmap.md#after-the-mvp-the-demo), steps
5 to 7). It also changes the agent's messages; see Consequences.

## Context

The demo lets anyone try the agent in a browser, without signing up, with at most 5
conversations a day in total, so that strangers cannot raise the cost of the model and web
search. It needs a server that runs the LangGraph graph and keeps each conversation between
messages, and a chat page that shows the questions and the report. Only the page is open to
the internet.

## Decision

- **Backend: [Aegra](https://github.com/aegra/aegra),** an open-source, self-hosted server for
  LangGraph agents under the Apache 2.0 licence. It serves the graph over the Agent Protocol,
  keeps the conversations in PostgreSQL, and replaces LangSmith Deployment, LangChain's own
  service, so the LangGraph SDK works with it unchanged.
- **Frontend: LangChain's [Agent Chat UI](https://github.com/langchain-ai/agent-chat-ui),** a
  Next.js chat page under the MIT licence, cloned into `demo/`. It talks to such a server
  through the LangGraph SDK.

Both are made for LangGraph and speak the same API, so the server and the chat are reused, not
written. The demo still needs its own rules, such as the daily limit and who can see or
continue a conversation. They belong to the demo's own setup of Aegra, its auth handlers, not
to the agent's code or the page. The page needs small changes of its own.

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

- Agent Chat UI reads LangChain messages from the state's `messages` key, so roadmap step 5
  changes the agent. In the code, `messages` will hold LangChain messages, and runs saved in
  the old `{role, text}` form will still load. In [the state](../architecture.md#the-state),
  `messages` will no longer be the input phase alone: the finished report is added once as one
  more agent message, and the `report` field stays for the CLI and the judges.
- The agent asks its questions with `interrupt()`, so the page answers a waiting run with a
  resume command, not with a new message. A failed service is not a message either, so the
  page takes its notice from the stream, as the CLI does.
- A finished conversation is public and stays. Other visitors see only its messages: the
  user's words, the questions and the report. The rest of the state, such as the page texts in
  `sources`, which have rights of their own ([data rights](../sources.md#data-rights)), stays
  hidden. Before a conversation starts, the page says that a finished conversation is public,
  the user's own words included.
- Three services to run: Aegra, PostgreSQL and the page. The page is a fork: TypeScript code
  in the repository, and its updates are merged by hand.

TODO: roadmap steps 5 to 7 implement this decision.
