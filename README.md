# Out of Frame

*The questions nobody showing you the home is obliged to ask.*

An AI agent that checks a Berlin address for what a property listing leaves out: nearby
industry, wastewater treatment plants, airports, major roads and railways, and planned
development. Every finding it reports cites its source.

## What it does

You give it an address or a listing. It asks where you travel regularly and when, then:

1. finds what is nearby on OpenStreetMap and in Berlin's development plans;
2. settles what each object is and whether it is in use, from its map data or by searching
   the web for it, and leaves an object unidentified when no page settles it;
3. plans your journeys there and back by public transport;
4. writes a report: what each object is, how far it is, why it matters to someone living
   there, and the source of each fact.

It writes in the language you write in.

It is a LangGraph agent on Claude Haiku 5.5, with Tavily for web search. Code decides what
runs next, except when the model stops searching for one object, checks that every finding
from a web search quotes its page word for word, and fills in the references. See the
[vision](docs/vision.md) and the [architecture](docs/architecture.md).

A language model writes the report, and it can be wrong: check what matters to you against
the sources it cites.

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

The offline checks need no keys: tests, the code graders and the task format.

```bash
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

## Status

The MVP is done: the CLI and its evals. Next is a live demo, a web page without sign-up; see
the [roadmap](docs/roadmap.md).

## License

[MIT](LICENSE)
