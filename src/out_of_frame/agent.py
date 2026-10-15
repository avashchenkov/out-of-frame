"""One run of the agent, from the user's first message to the report: the LangGraph graph of
docs/architecture.md#one-run."""

import datetime as dt
import itertools
import logging
import uuid
from functools import cache

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, Send, interrupt

from out_of_frame import (
    conversation,
    geocoding,
    grounding,
    investigation,
    map_objects,
    plans,
    report,
    transit,
    triage,
)
from out_of_frame.config import INVESTIGATIONS_AT_ONCE
from out_of_frame.investigation import Context
from out_of_frame.record import Record
from out_of_frame.state import Address, MapObject, Message, ObjectSourceKind, RunState
from out_of_frame.web_search import WebSearch

log = logging.getLogger(__name__)


class ObjectToInvestigate(Record):
    """What one investigation gets from the run: its own input, not the run state, so that
    investigations can run in parallel."""

    map_object: MapObject
    source_kind: ObjectSourceKind


# The steps that research starts with, in parallel, once the input is complete.
RESEARCH_STARTS = ["get_map_objects", "get_plans", "plan_journeys"]


class UnansweredQuestionError(Exception):
    """The agent asked a question after the user's replies had run out."""


def run(
    messages: list[str],
    date: dt.date,
    web_search: WebSearch,
    input_only: bool = False,
    config: RunnableConfig | None = None,
) -> RunState:
    """A run without a person: the first message starts it, and each next one answers the
    agent's next question, as in the evals. With input_only, the run stops once the input is
    complete, before research starts, as in the input loop suite. A caller that gives the
    run's thread can read the state where the run stopped, even after an error."""
    graph, config = build_graph(), config or start_thread()
    command: RunState | Command = start(messages[0])
    stop = RESEARCH_STARTS if input_only else None
    for reply in [*messages[1:], None]:
        graph.invoke(command, config, context=Context(date, web_search), interrupt_before=stop)
        question = find_question(graph, config)
        if question is None:
            break
        if reply is None:
            raise UnansweredQuestionError(question)
        command = Command(resume=reply)
    return RunState.model_validate(graph.get_state(config).values)


def start(message: str) -> RunState:
    """The state that a run starts from: the user's first message."""
    return RunState(messages=[Message(role="user", text=message)])


def start_thread() -> RunnableConfig:
    """The config of a new run: the graph keeps each run's state under its own thread."""
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


def find_question(graph, config: RunnableConfig) -> str | None:
    """The question that the run waits to have answered, if it waits."""
    interrupts = graph.get_state(config).interrupts
    return interrupts[0].value if interrupts else None


@cache
def build_graph():
    """The graph, which keeps the state of each run in memory, so that a run can wait for the
    user's answer and go on; a known MVP limitation, see docs/roadmap.md, step 7."""
    if INVESTIGATIONS_AT_ONCE < 2:  # a stream with its subgraphs takes one, see config.py
        raise ValueError("OUT_OF_FRAME_INVESTIGATIONS_AT_ONCE must be at least 2")
    builder = StateGraph(RunState, context_schema=Context)
    builder.add_node(extract_input)
    builder.add_node(geocode_input)
    builder.add_node(ask_for_missing)
    builder.add_node(wait_for_answer)
    builder.add_node(get_map_objects)
    builder.add_node(get_plans)
    builder.add_node(plan_journeys)
    builder.add_node(triage_objects)
    builder.add_node(get_addresses)
    builder.add_node(investigate_object)
    builder.add_node(write_report)
    builder.add_node(fill_references)
    builder.add_edge(START, "extract_input")
    builder.add_edge("extract_input", "geocode_input")
    builder.add_conditional_edges(
        "geocode_input", check_input, ["ask_for_missing", *RESEARCH_STARTS]
    )
    builder.add_edge("ask_for_missing", "wait_for_answer")
    builder.add_edge("wait_for_answer", "extract_input")
    builder.add_edge(RESEARCH_STARTS, "triage_objects")  # once the map, plans and journeys are in
    builder.add_edge("triage_objects", "get_addresses")
    builder.add_conditional_edges(
        "get_addresses", send_each_object_to_investigation, ["investigate_object", "write_report"]
    )
    builder.add_edge("investigate_object", "write_report")  # once every investigation has ended
    builder.add_edge("write_report", "fill_references")
    builder.add_edge("fill_references", END)
    # The state's own records, which the checkpointer may load back without a warning.
    records = ["Address", "Destination", "Finding", "Journey", "MapObject", "Message", "Source"]
    serde = JsonPlusSerializer(allowed_msgpack_modules=[("out_of_frame.state", r) for r in records])
    graph = builder.compile(checkpointer=InMemorySaver(serde=serde))
    return graph.with_config(max_concurrency=INVESTIGATIONS_AT_ONCE)


def extract_input(state: RunState) -> dict:
    """The changes that the user's last message makes, see conversation.apply; everything else
    stays as it was."""
    return conversation.apply(conversation.extract(state), state)


def geocode_input(state: RunState) -> dict:
    """Every address geocoded again after each message, and each response kept, so that code
    can say why an address does not resolve. The property must be in Berlin; a destination may
    be anywhere."""
    numbers = itertools.count(1 + sum(source.kind == "geocoding" for source in state.sources))
    sources = []

    def geocode(address: Address | None, berlin_only: bool) -> Address | None:
        if address is None:
            return None
        source_id = f"nominatim-{next(numbers)}"
        geocoded, source = geocoding.geocode(address.text, source_id, berlin_only=berlin_only)
        sources.append(source)
        return geocoded

    changes: dict = {"property": geocode(state.property, berlin_only=True)}
    if state.destinations is not None:
        changes["destinations"] = [
            destination.model_copy(
                update={"address": geocode(destination.address, berlin_only=False)}
            )
            for destination in state.destinations
        ]
    return changes | {"sources": sources}


def check_input(state: RunState) -> str | list[str]:
    """Research starts once nothing is missing or unclear in the input; code decides it."""
    return "ask_for_missing" if conversation.find_missing(state) else RESEARCH_STARTS


def ask_for_missing(state: RunState) -> dict:
    question = conversation.ask(state, conversation.find_missing(state))
    return {"messages": [Message(role="agent", text=question)]}


def wait_for_answer(state: RunState) -> dict:
    """The run waits here for the user's answer to the question. On resume LangGraph runs this
    node again from its start, so it makes no model call."""
    answer = interrupt(state.messages[-1].text)
    return {"messages": [Message(role="user", text=answer)]}


def get_map_objects(state: RunState) -> dict:
    """The nearest map objects of each category around the property. If Overpass fails, the
    map part of the report is missing."""
    assert state.property is not None and state.property.coordinates is not None  # see check_input
    try:
        found, source = map_objects.fetch_map_objects(state.property.coordinates)
    except map_objects.MapError as error:
        log.warning("the map failed: %s", error)
        return {"failures": ["map"]}
    return {"map_objects": found, "sources": [source]}


def get_plans(state: RunState) -> dict:
    """The nearest development plans around the property. If the WFS fails, the plans part of
    the report is missing."""
    assert state.property is not None and state.property.coordinates is not None  # see check_input
    try:
        found, source = plans.fetch_plans(state.property.coordinates)
    except plans.PlansError as error:
        log.warning("the plans failed: %s", error)
        return {"failures": ["plans"]}
    return {"map_objects": found, "sources": [source]}


def plan_journeys(state: RunState, runtime: Runtime[Context]) -> dict:
    """The journeys there and back for each destination, none if the user travels nowhere. If
    Transitous fails, the journeys it could not plan are unavailable, and the others stay."""
    assert state.property is not None and state.property.coordinates is not None  # see check_input
    if not state.destinations:
        return {}
    home, date = state.property.coordinates, runtime.context.date
    journeys = transit.plan_journeys(home, state.destinations, date)
    failed = any(journey.outcome == "unavailable" for journey in journeys)
    return {"journeys": journeys, "failures": ["transit"] if failed else []}


def triage_objects(state: RunState) -> dict:
    """Triage of each object that code does not send to investigation, one at a time: a clear
    one gets its finding, and any other goes to investigation."""
    checked = [
        triage.triage(o)
        for o in state.map_objects
        if not is_sent_by_code(o, state.find_source_kind(o))
    ]
    return {"findings": [finding for finding in checked if finding is not None]}


def get_addresses(state: RunState) -> dict:
    """The addresses of the map objects to investigate, from one query, in place of the objects
    without them. A plan has none: it is found by its number. If Overpass fails, the objects
    are investigated without addresses: the map part of the report stays."""
    chosen = [o for o in choose_objects_to_investigate(state) if state.find_source_kind(o) == "map"]
    try:
        addresses = map_objects.fetch_addresses(chosen, state.sources)
    except map_objects.MapError as error:
        log.warning("the addresses failed, so the objects are investigated without them: %s", error)
        return {}
    found = [
        o.model_copy(update={"addresses": addresses[o.id]}) for o in chosen if o.id in addresses
    ]
    return {"map_objects": found}


def choose_objects_to_investigate(state: RunState) -> list[MapObject]:
    """Every object without a finding yet, nearest first: those that code sends to
    investigation and those that triage could not settle. At most five per category, as the
    map and the plans keep no more."""
    settled = {finding.map_object_id for finding in state.findings}
    chosen = [o for o in state.map_objects if o.id not in settled]
    return sorted(chosen, key=lambda o: o.distance_from_property_m)


def is_sent_by_code(map_object: MapObject, source_kind: ObjectSourceKind) -> bool:
    """Every plan and every industrial object goes to investigation, even with a name and
    complete data, and so does any object that is proposed or under construction; triage
    checks the others."""
    tags = map_object.details
    if source_kind == "plans" or tags["category"] == "industry":
        return True
    return map_objects.find_stage(tags) != "built"


def send_each_object_to_investigation(state: RunState) -> list[Send] | str:
    chosen = choose_objects_to_investigate(state)
    if not chosen:
        return "write_report"
    return [
        Send(
            "investigate_object",
            ObjectToInvestigate(map_object=o, source_kind=state.find_source_kind(o)),
        )
        for o in chosen
    ]


def investigate_object(state: ObjectToInvestigate, runtime: Runtime[Context]) -> dict:
    """The investigation of one object; its finding, the page the finding cites, and a web
    search failure go into the run state. Each investigation numbers its pages from web-1, so
    in the run state a page's ID also names its object, such as osm-way-1/web-1."""
    context = runtime.context
    end = investigation.investigate(
        state.map_object, state.source_kind, context.date, context.web_search
    )
    assert end.finding is not None  # every path through the subgraph ends with a finding
    cited = grounding.collect_cited_page(end.finding.evidence_id, end.pages)
    sources = [page.model_copy(update={"id": f"{state.map_object.id}/{page.id}"}) for page in cited]
    evidence_id = end.finding.evidence_id
    if cited:  # the finding cites a page, not the map
        evidence_id = f"{state.map_object.id}/{evidence_id}"
    return {
        "findings": [end.finding.model_copy(update={"evidence_id": evidence_id})],
        "sources": sources,
        "failures": ["web search"] if end.web_search_failed else [],
    }


def write_report(state: RunState, runtime: Runtime[Context]) -> dict:
    """The model's draft, which the evals grade before code fills in its references."""
    return {"report": report.write_report(state, runtime.context.date)}


def fill_references(state: RunState) -> dict:
    assert state.report is not None  # write_report comes first
    return {"report": report.fill_references(state.report, state)}
