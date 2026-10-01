# 1. Build the agent with LangGraph

Status: accepted, 2026-09-25

## Context

The run described in [architecture.md](../architecture.md) needs:

- one state shared by all phases;
- questions to the user that pause the run until the answer comes;
- research branches that run in parallel;
- one investigation per object, each in its own context;
- saving the state during a run.

## Decision

Use LangGraph for the flow: the state, the branches, the pauses and the parallel
investigations. Source clients, the grounding check and other logic stay plain Python.

LangGraph is built for this kind of flow: code-driven routing, pauses for user input,
parallel branches and agentic loops, all over one state. Each need above maps to one of its
features: a typed state; `interrupt()` for questions to the user; parallel edges for the
research branches; `Send` to start one investigation subgraph per object; a checkpointer to
save the run. LangGraph handles the orchestration, so the work goes into the logic inside
the nodes.

## Alternatives

- **Plain Python with the Anthropic SDK:** fewer dependencies and full control, but we would
  write the routing, the pauses, the parallel investigations and saving the state ourselves.
  The flow needs orchestration either way, and it needs no more flexibility than LangGraph
  gives.
- **Claude Agent SDK, OpenAI Agents SDK:** built around a loop in which the model chooses the
  tools and the next step. That fits the investigation loop only. The input phase, the research
  branches and the report are fixed by code, so they would be written by hand around the
  SDK, as in the first alternative.
- **pydantic-graph, with PydanticAI for model calls:** typed state, nodes and edges. A
  workable option, but for flows built as a graph LangGraph is the more common choice.

## Consequences

- The flow is built on LangGraph's state, nodes and edges. Replacing LangGraph means
  rewriting the orchestration code.
- Parallel branches and investigations write to the same state. Each shared field needs a
  rule for merging their updates; without one, LangGraph rejects the update.
- Pauses need a checkpointer and a thread ID. When a run resumes, the paused node starts again
  from the beginning, so the work before the pause must be safe to repeat.
- Each investigation needs its own subgraph state, and only the finding, the pages it cites
  and a web search failure return to the main state. `Send` starts the subgraph but does not
  keep its transcript out of the main state by itself.
