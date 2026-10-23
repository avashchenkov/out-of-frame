# The compiled graph

The two graphs as LangGraph compiles them from the code and draws them itself, so they cannot
drift from it: a test fails when the code and this page differ. They show the nodes and the
edges only. What each step does, its data source and who decides what are in the
[architecture](architecture.md). A solid edge is always taken; code picks a dashed one at run
time.

## One run

The graph of `agent.build_graph()`. Each object chosen for investigation goes to
`investigate_object`, in parallel with the others, and that node runs the investigation graph
below.

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	extract_input(extract_input)
	detect_language(detect_language)
	geocode_input(geocode_input)
	ask_for_missing(ask_for_missing)
	wait_for_answer(wait_for_answer)
	get_map_objects(get_map_objects)
	get_plans(get_plans)
	plan_journeys(plan_journeys)
	triage_objects(triage_objects)
	get_addresses(get_addresses)
	investigate_object(investigate_object)
	write_report(write_report)
	fill_references(fill_references)
	__end__([<p>__end__</p>]):::last
	__start__ --> extract_input;
	ask_for_missing --> wait_for_answer;
	detect_language --> geocode_input;
	extract_input --> detect_language;
	geocode_input -.-> ask_for_missing;
	geocode_input -.-> get_map_objects;
	geocode_input -.-> get_plans;
	geocode_input -.-> plan_journeys;
	get_addresses -.-> investigate_object;
	get_addresses -.-> write_report;
	get_map_objects --> triage_objects;
	get_plans --> triage_objects;
	investigate_object --> write_report;
	plan_journeys --> triage_objects;
	triage_objects --> get_addresses;
	wait_for_answer --> extract_input;
	write_report --> fill_references;
	fill_references --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```

## The investigation

The graph of `investigation.build_graph()`, run once for each object chosen for
investigation. Before each call to the model, code checks the cap of tool calls on the edge
and goes to `write_finding` once it is reached; this is why both `__start__` and `run_tool`
have a dashed edge to it. A run starts with no calls, so with a cap of 1 or more it always
goes to `search_or_stop` first.

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	search_or_stop(search_or_stop)
	run_tool(run_tool)
	write_finding(write_finding)
	check_grounding(check_grounding)
	__end__([<p>__end__</p>]):::last
	__start__ -.-> search_or_stop;
	__start__ -.-> write_finding;
	check_grounding -.-> __end__;
	check_grounding -.-> write_finding;
	run_tool -.-> __end__;
	run_tool -.-> search_or_stop;
	run_tool -.-> write_finding;
	search_or_stop -.-> run_tool;
	search_or_stop -.-> write_finding;
	write_finding --> check_grounding;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```
