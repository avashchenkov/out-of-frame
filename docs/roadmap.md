# Roadmap

The MVP and the demo are complete, and the demo is live. This roadmap is closed.
The [agent architecture](architecture.md), [demo architecture](demo-architecture.md) and
[eval architecture](eval-architecture.md) describe the design and checks.

Step numbers are retained for existing references. Detailed substeps cited by older eval
reports are in the [earlier roadmap](https://github.com/avashchenkov/out-of-frame/blob/27a451ca74a0191048b98fe7021945f888037d82/docs/roadmap.md).

## MVP

| Step | Status | Result |
|---|---|---|
| 1–4 | ✅ | **Foundation:** repository, research categories and radii, an Overpass spike, and the first eval tasks and runner. |
| 5 | ✅ | **Investigate one object:** a CLI report backed by live web research, with source checks, a tool-call limit and a prompt injection check. |
| 6 | ✅ | **Research the surroundings:** group map elements, keep the nearest objects, triage clear ones and investigate the rest in parallel. Reports retain unknowns and show source failures. |
| 7 | ✅ | **Input conversation:** extract and geocode the address, clarify ambiguous input and pause for replies. |
| 8 | ✅ | **Development plans:** query Berlin's B-Plan WFS; report what a plan allows or is meant to allow, and whether building has started, apart from its legal status. |
| 9 | ✅ | **Commute:** collect destinations and departure times; add public transport journeys there and back through Transitous. |
| 10 | ✅ | **Evaluation and quality fixes:** prepare labels, calibrate three report judges, run component and live end-to-end suites, and improve classification, evidence use and report wording. Publish results and limitations. |

The [MVP results](evals/2026-10-21-mvp-eval-results.md) record the before/after comparison,
excluded labels, remaining errors and cost. The [quality audit](evals/2026-10-19-agent-quality-audit.md)
records why the fixes were chosen, including the model's reasoning effort and the retry for
rejected findings.

## After the MVP: the demo

| Step | Status | Result |
|---|---|---|
| 1 | ✅ | **Held-out check:** test two new addresses before changing the report, with no tuning on them. [Results](evals/2026-10-21-mvp-eval-results.md#held-out-check) published on 2026-10-22. |
| 2–4 | ✅ | **Readable reports:** Markdown sections, named source links, an AI notice and licence credits; questions and reports in the user's language. |
| 5 | ✅ | **Demo design:** services, private access, limits and retention defined in the [architecture](demo-architecture.md), [ADR 4](adr/0004-demo-aegra-and-agent-chat-ui.md) and [launch checklist](demo-launch-checklist.md). |
| 6 | ✅ | **Agent service:** Aegra with PostgreSQL and Redis; private chat ownership, quotas, recovery, cancellation and deletion. Restart and cleanup checks run locally and in CI. |
| 7 | ✅ | **Web interface:** private chat, progress, reconnection, retry and deletion; filtered browser responses, five recorded examples and legal notices. |
| 8 | ✅ | **Deployment:** one VPS with Docker Compose and HTTPS. Launch checklist and live trial completed on 2026-10-25, including report links and chat deletion; live input enabled. |
| 9 | ✅ | **Public documentation:** README, design decisions, results, scope, data sources and licences. |
| 10 | ✅ | **Traffic limits:** at most 10 progress streams across visitors and 2 per identity, and at most 20 API requests per second. |
| 11 | ✅ | **Commute limit:** at most two destinations by default; ask the user which to keep before calling sources. |
| 12 | ✅ | **Input recovery:** the extraction also takes an earlier answer that the input missed; input loop cases I4–I7. |
| 13 | ✅ | **Recorded-example review:** a visible note explains the known stale Philip Morris claim in the Neuköllnische Allee example, preserving the original report. |

## Scope

Further eval tasks are added when an observed failure needs them; there is no planned phase
to expand every designed suite. Deeper search, a stronger model and multiple sources per finding
remain outside the MVP. A separate Docker image for the CLI was dropped; the CLI uses `uv`,
and Docker is used for the demo.
