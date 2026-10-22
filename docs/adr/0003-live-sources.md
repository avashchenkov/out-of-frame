# 3. Live sources instead of an index of our own

Status: accepted, 2026-09-21. Written on 2026-10-22, after the implementation.

## Context

Agents that answer from documents often keep an index of their own, such as a vector store or
a crawled copy of web pages, and search it during a run. This agent needs two kinds of
knowledge: its rules, what to look for and how far
([research_scope.yaml](../../src/out_of_frame/data/research_scope.yaml)), and the facts about
one place, which change over time.

## Decision

No index of our own.

- The rules are small. Code applies the categories, the radii and the map tags. The meanings
  of the types and statuses, and the rules for a finding, are written out in the prompts.
- The facts come from live sources during the run ([sources.md](../sources.md)): geocoding
  turns the address into coordinates, and the map, the plans and the journeys are queried by
  location.
- Web search runs live and only in an investigation ([ADR 2](0002-why-an-agent.md)); code
  and triage do not search.

## Alternatives

- **A fixed corpus of our own:** crawl pages about Berlin sites once, index them, and search
  the index during a run. A fixed corpus can be tested in depth, with the same source data in
  each run. But the pages that matter for an address are not known in advance, so the crawl
  would have to be wide. The corpus also goes stale, and a stale fact, such as a factory that
  has closed, is the kind of error the agent exists to avoid. Building it and keeping it fresh
  would be a project of its own.
- **A local copy of the map and plan data,** such as a Berlin extract of OpenStreetMap in our
  own database: it does not depend on the public map server, which failed in three trials of
  the MVP run. But it must be refreshed and adds a database to run, while the public services
  already answer by location.

## Consequences

- The report shows what the sources say on the day of the run.
- A run cannot be repeated exactly, because the web and the map change. Tasks with fixed
  source data check the model steps without the live sources; live end-to-end tasks show how
  the whole agent does on the day they run.
