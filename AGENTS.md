# Agent instructions

Out of Frame is an AI agent that checks a Berlin address for what a property listing leaves out.
See [README.md](README.md).

## Read first

Before any change larger than a typo fix, read:

- [docs/vision.md](docs/vision.md): what the agent is for and what is out of scope;
- [docs/architecture.md](docs/architecture.md): how a run works and who decides what;
- [docs/eval-architecture.md](docs/eval-architecture.md): how the agent is measured, and the
  eval tasks to prepare before each behaviour;
- [docs/roadmap.md](docs/roadmap.md): the implementation steps and which are done.

Do not change vision.md, architecture.md or eval-architecture.md on your own. If a change conflicts with them, stop
and ask. Continue only if the user approves.

When a step is committed, mark it done in the roadmap with ✅. If the plan changes, propose
an update to the roadmap.

## Talking to the user

Keep answers short: the big picture first, and keep it short. User will ask you for the details if needed.

Say so, unasked, when more effort on a part stops paying off: name what is already good
enough and the next useful step instead. "Good enough, keep moving" is the right error to
make.

## Git

Never commit or push without a direct request from the user. When a change is ready, list the
changed files, propose a commit message and stop.

Commit messages follow Conventional Commits (`feat`, `fix`, `docs`, `test`, `refactor`,
`build`, `ci`, `chore`): a short imperative subject, lowercase, no trailing full stop. No AI
co-author trailers.

## Conventions

- English everywhere in the repository: code, comments, docs and commit messages.
- Write plain international English: short sentences, common words, no idioms. Many readers
  are not native speakers. Keep prose brief.
- The README describes only what already exists.
- Track implementation plans and completion in `docs/roadmap.md`. Architecture docs and ADRs
  record design and decisions; update them when the design changes, without task statuses.
  Launch checklists define requirements; track their completion in the roadmap too.
- Use `TODO:` for specific unfinished work in code or eval tasks, not for unimplemented
  design requirements throughout the documentation.

## Development

Python 3.14 with uv. Add dependencies with `uv add` and run commands with `uv run`. Do not use pip.

- Never open, print or read `.env`; `.env.example` is fine. Tests and code graders run without
  keys.
- Ask before any run that calls a paid API, the model or web search, with a cost estimate.
- Agent runtime settings live in `src/out_of_frame/config.py` and the environment; never
  hard-code them. Keep evaluation-only settings outside the runtime package, in
  `evals/config.py`, with their example environment in `evals/.env.example`.
- Hand work to another agent or model, such as Codex or Grok, only when the user asks. It works
  read-only and does not hand the work on.
