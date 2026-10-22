# 2. An agent for the investigation, a workflow for the rest

Status: accepted, 2026-09-21. Written on 2026-10-21, after the implementation.

Terms follow Anthropic's
[Building effective agents](https://www.anthropic.com/engineering/building-effective-agents).
A *workflow* runs model calls and tools on paths fixed in code. An *agent* is a system in
which the model directs its own steps and tool use: it chooses the next step and when to stop.

## Context

What the agent is for is in [vision.md](../vision.md#why-an-agent). The facts about a place
come from sources of different shape: the map gives tags, the plans give fixed fields, and web
pages give free text. They overlap but name things in different ways: an unnamed industrial
area on the map, a company's name on a web page, a plan by its number. A search may find the
object, another one with a similar name, or nothing.

Most of a run reads the map, the plans and the journeys by fixed rules. One part does not:
telling which page is about which object, and what the pages and the data together say about
it, such as what it is, whether it is in use or, for a plan, whether building has started.
Which searches this takes, and how many, is not known in advance.

## Decision

The agent is the investigation loop of an unclear object. The model chooses what to search for
and which page to read, and decides whether to search again or stop, within three tool calls
by default ([config.py](../../src/out_of_frame/config.py)).

The rest of the run is a workflow: code decides what runs next
([Who decides](../architecture.md#who-decides)), and the model does single steps in fixed
places:

- the input: it reads the user's message and asks for what is missing;
- triage: one call per map object that code neither settles itself, as it does a railway, nor
  sends to investigation; it takes the type from the name, the tags and what it knows, and the
  status from the tags alone, with no web check; a conflict with what it knows sends the
  object to investigation;
- each investigation: a check of each snippet and page for prompt injection before the loop
  sees it, and one call that writes the finding; a finding that the grounding check rejects
  gets one more try with the reason;
- the report: one call; code fills in the references and asks for one more draft if a citation
  is wrong or an object is left out.

Code keeps the nearest five objects per map category and the nearest five plans, by default,
and the report says so. Map, plan and journey queries are fixed code, and the map and plan
searches have fixed radii.

A fixed path is predictable, cheap and easy to test, and a model does a narrow step well. The
agent is used where the next action depends on the text just found: search again, try another
query, read a result or stop.

## Alternatives

- **A workflow without an agent:** the investigation as fixed steps, such as two searches and
  one page read. A model call at each step could still write the query and pick the page, but
  code would choose what comes next. Each gap in the evidence is itself a reading of the text,
  such as a status that is not settled, results about another site or a snippet that lacks
  the facts, so the rules for code would never form a full list. A model call that names the
  gap, for code to branch on, is the same choice made by the model, with more code. The eval
  architecture defines these choices as tasks, for example
  [S5](../eval-architecture.md#search) and [N2 and N5](../eval-architecture.md#enough); the
  Enough tasks N1–N6 run in the MVP, S5 does not.
- **A larger agent:** the agent could also take other steps, such as triage with its own web
  search, or an input phase that decides by itself when the input is complete. Neither is
  needed: unclear objects already go to investigation, and code checks the input by explicit
  rules. Each would add decisions to test, and triage with search would add searches to pay
  for. The article advises the simplest solution that works and more autonomy only where it is
  needed, so the agent is kept to the one step that needs it.

## Consequences

- More design work and less flexibility: changing the graph or the state needs a change of
  code.
- The choice follows the article's advice and is not measured: no baseline was built.
- Two runs on the same address can search in different ways and reach different findings.
  So evals run each live task three times and report the labels that are unstable, and each
  run pays for its searches ([MVP eval results](../evals/2026-10-21-mvp-eval-results.md)).
- Any model step that reads web text can be misled by prompt injection. In the agent the risk
  is larger: injected text can steer its next step, for example make it stop early or search
  for something else, not only change one answer. So a separate model call checks each snippet
  and page before the loop sees it, one more call each
  ([Prompt injection](../architecture.md#prompt-injection)).
