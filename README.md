# <img src="docs/assets/logo.svg" alt="" width="40" align="center"> Out of Frame

*The questions nobody showing you the home is obliged to ask.*

[![CI](https://github.com/avashchenkov/out-of-frame/actions/workflows/ci.yml/badge.svg)](https://github.com/avashchenkov/out-of-frame/actions/workflows/ci.yml)

An AI agent that checks a Berlin address for what a property listing leaves out: nearby
industry, wastewater treatment plants, airports, major roads and railways, and planned
development. Every finding it reports cites its source.

**Demo: <https://outofframe.hooraytalk.com>**, with five recorded examples and a private chat
without sign-up.

## What it does

You give it an address or a listing. It asks where you travel regularly and when, then:

1. finds what is nearby on OpenStreetMap and in Berlin's development plans;
2. settles what each object is and whether it is in use, from its map data or by searching
   the web for it, and leaves an object unidentified when no page settles it;
3. plans your journeys there and back by public transport, for up to two destinations by default;
4. writes a report: what each object is, how far it is, why it matters to someone living
   there, and the source of each fact.

It writes in the language you write in.

It is a LangGraph agent on Claude Haiku 5.5, with Tavily for web search. Code decides what
runs next; only the model decides when to stop searching for one object. Code also checks that
every finding from a web search quotes its page word for word, and fills in the references. See
the
[vision](docs/vision.md) and the [architecture](docs/architecture.md).

A language model writes the report, and it can be wrong: check what matters to you against
the sources it cites.

## Design choices

- **An agent only where it is needed.** The model directs its own steps only in the
  investigation of an unclear object; the rest is a workflow fixed in code
  ([ADR 2](docs/adr/0002-why-an-agent.md)).
- **LangGraph** for the state, the pauses for user input and the parallel investigations
  ([ADR 1](docs/adr/0001-langgraph.md)).
- **Live sources, no index of our own:** no vector store or crawled copy of the web; the facts
  about a place come from the map, the plans, the journey planner and web search during the
  run ([ADR 3](docs/adr/0003-live-sources.md)).
- **Grounded findings:** after a web search, code checks that the key facts of a finding
  appear word for word in the page, map or plan data it cites. Each object in the report
  links to its sources.
- **A prompt injection check:** a separate model call checks each search result and page
  before the investigation reads it.
- **No MCP:** there are no clients outside the system to serve tools to. The two LLM tools,
  search and extract, call Tavily through a small facade over its Python library: it fixes
  the settings, passes on only URLs and text, and has a stub for tests. Tavily's MCP server
  would only add the overhead of an MCP client and gain nothing.
- **No baseline:** the choice of an agent for one step follows Anthropic's
  [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents);
  it was not measured against a simpler design.
- **The demo on Aegra and Agent Chat UI,** self-hosted on one server
  ([ADR 4](docs/adr/0004-demo-aegra-and-agent-chat-ui.md)).

## Out of scope

It reports facts and gives no advice: it does not say whether to buy or rent, gives no overall
score and does not look at prices or rents. It covers Berlin only. It is not a product or a
public service; the demo, with its daily limit, only shows how it works. See the
[vision](docs/vision.md#out-of-scope).

## Run it

You need [uv](https://docs.astral.sh/uv/) and your own API keys for
[Anthropic](https://console.anthropic.com/settings/keys) and [Tavily](https://app.tavily.com).

```bash
git clone https://github.com/avashchenkov/out-of-frame.git
cd out-of-frame
uv sync
cp .env.example .env
```

Fill in `ANTHROPIC_API_KEY` and `TAVILY_API_KEY` in `.env`, then:

```bash
uv run --env-file .env out-of-frame "Freiheit 22, 13597 Berlin"
```

The agent asks its questions in the terminal and prints the report. A run takes a few minutes
and costs about $0.25 in API calls. The map, plans and journey planner are free public
services. Only the two keys are required; every other setting has a default in
`src/out_of_frame/config.py`, and `.env.example` shows the common ones.

## Evals

The offline checks need no keys: tests, the code graders and the task format. The demo tests
also need Aegra, from the `demo` extra:

```bash
uv sync --extra demo
uv run pytest
```

Each part of the agent has its own suite, and five Berlin addresses, E1–E5, test it end to
end against labels that several models checked, with a person settling where they disagree.
A suite runs each task k times:

```bash
uv run --env-file .env python -m evals.run --part draft_finding --k 3
```

The parts are `check_page`, `draft_finding`, `decide_enough`, `investigate`,
`triage_object`, `write_report`, `run_input_loop` and `run_end_to_end`. The end-to-end suite
runs live and costs about $4 at k=3. Results are saved in `evals/results/`, which git ignores.

`write_report` and `run_end_to_end` are graded by LLM judges too, and run only if each judge
is the version that passed calibration. That check needs the saved runs the judges were
calibrated on, which hold the web pages the agent read and so stay local, out of the
repository: on a fresh clone these two suites stop before any paid call. The other suites run
as they are.

- [MVP eval results](docs/evals/2026-10-21-mvp-eval-results.md): every suite before and after
  the fixes, the failures left, the labels left out and the known limitations.
- [Eval architecture](docs/eval-architecture.md): what each suite measures and how it is
  graded, including the LLM judges and their calibration.

## The demo

The [demo](https://outofframe.hooraytalk.com) has two parts:

- **Five recorded examples,** each with the date of its research, open to everyone without a
  chat or limits. The author reviewed each one before publishing it; they are kept in
  [recorded-examples.json](demo/frontend/src/data/recorded-examples.json).
- **A private live chat** without sign-up. An essential cookie gives one browser access to
  its own chat, and no other visitor can open it. Daily and per-browser limits keep the cost
  bounded. Access ends 30 days after the first message, and automatic cleanup then deletes
  the chat from our server; New chat or Delete chat deletes it earlier. The providers keep
  their own copies for their own periods. Visitor reports are never published and never
  added to the repository.

Like the CLI, each report says that a language model wrote it and that its facts should be
checked against the sources it cites. The [demo architecture](docs/demo-architecture.md)
covers the services, the limits and the retention; [demo/README.md](demo/README.md) covers
running and deploying it.

## Legal frame and data sources

The agent reports facts with their sources and gives no advice. The demo has
[service terms](https://outofframe.hooraytalk.com/terms), a
[Privacy notice](https://outofframe.hooraytalk.com/privacy) and an
[Impressum](https://outofframe.hooraytalk.com/impressum); the
[launch checklist](docs/demo-launch-checklist.md) lists what they had to cover.

The data comes from OpenStreetMap through Nominatim and Overpass (ODbL), Berlin's
development plans (dl-de/zero-2.0), Transitous (non-commercial use only, open-source code and
a link to its sources) and web pages found by Tavily, which keep the rights of their sites.
Each report cites its sources and credits OpenStreetMap, and Transitous's sources when it
has journeys. See
[sources.md](docs/sources.md#data-rights).

## License

[MIT](LICENSE)
