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
npm run lint
npm run format:check
```

The thread layout, scroll behaviour and Markdown renderer are adapted from
[Agent Chat UI](https://github.com/langchain-ai/agent-chat-ui/tree/7a503412aeeb4534a24b04bd97b618ee3871821e),
commit `7a503412aeeb4534a24b04bd97b618ee3871821e`.
Its MIT licence is retained in [LICENSE](LICENSE).
Upstream source files: `src/components/thread/index.tsx`,
`src/components/thread/messages/human.tsx` and `src/components/thread/markdown-text.tsx`.
This version keeps text messages, automatic scrolling and GitHub-flavoured Markdown.
It has no server selection, thread history, branching, message editing or file uploads.
