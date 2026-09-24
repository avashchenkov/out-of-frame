# Agent instructions

Out of Frame is an AI agent that checks a Berlin address for what a flat listing leaves out.
See [README.md](README.md).

## Read first

Before any change larger than a typo fix, read:

- [docs/vision.md](docs/vision.md): what the agent is for and what is out of scope;
- [docs/architecture.md](docs/architecture.md): how a run works and who decides what.

Do not change these two documents on your own. If a change conflicts with them, stop and ask.
Continue only if the user approves.

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
