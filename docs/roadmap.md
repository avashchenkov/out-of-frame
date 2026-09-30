# Roadmap

The implementation steps, in order.

1. ✅ **Repository setup.**
2. ✅ **Checklist.** Each checked class with its radius, its source and why it matters. Kept as
   data.
3. ✅ **Spike.** How many objects of each class does Overpass return, and how many have no
   name? This sets the investigation cap per class. Exploratory scripts live in `spikes/`, one
   folder per question, each with a dated note of its findings:
   [overpass-counts](../spikes/overpass-counts/findings-2026-09-25.md). The findings may change
   the checklist. The scripts stay outside the checks and are never extended.
4. **Evals.** `docs/eval-architecture.md`: how each step of the run is measured. Then the
   tasks with truth labels, committed before any agent code. Labels come from real-world
   evidence, not from the map data. Tests never read them. Define the finding type and status
   vocabularies in `src/out_of_frame/data/checklist.yaml` alongside these tasks; the agent and
   evals share the vocabulary, not the truth labels.
5. **First slice, without the graph.** Address → map objects → report with sources, as a CLI.
   With tests, source failures included, and CI.
6. **Eval harness.** It runs the tasks from step 4 and grades them. Each code grader has its
   own tests. The first run covers the tasks the first slice can already run. From here on,
   every step ends with a run of the tasks that can run by then.
7. **The graph** ([ADR 1](adr/0001-langgraph.md)): input questions and the investigation
   loop. The loop is tested on the search results saved with the step 4 tasks. The run
   states in `evals/states/` follow the [state model](architecture.md#the-state), not
   LangGraph classes; this step adds the code that loads them into the graph state.
8. **Remaining sources,** one at a time: Transitous, the B-Plan WFS and web search. With web
   search come the prompt injection guards in code. The injection tasks in the input and
   investigation suites measure how often the model is still misled.
9. **Judge calibration, then the full eval run.** Each LLM judge is checked against human
   grades; until then, only code-graded scores are quoted. The full run covers all tasks,
   several trials each. Results are published with the failures.
