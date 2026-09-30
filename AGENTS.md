# Agent instructions

Out of Frame is an AI agent that checks a Berlin address for what a property listing leaves out.
See [README.md](README.md).

## Read first

Before any change larger than a typo fix, read:

- [docs/vision.md](docs/vision.md): what the agent is for and what is out of scope;
- [docs/architecture.md](docs/architecture.md): how a run works and who decides what;
- [docs/roadmap.md](docs/roadmap.md): the implementation steps and which are done.

Do not change vision.md or architecture.md on your own. If a change conflicts with them, stop
and ask. Continue only if the user approves.

When a step is committed, mark it done in the roadmap with ✅. If the plan changes, propose
an update to the roadmap.

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
- In docs and code, mark anything planned but not done yet with `TODO:`, so that a search
  finds it. The roadmap is the exception: it is the plan itself.

## Development

Python 3.14 with uv. Add dependencies with `uv add` and run commands with `uv run`. Do not use pip.
