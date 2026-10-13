"""One run of the agent, from the property's address to the report: the LangGraph graph of
docs/architecture.md#one-run.

TODO: the input conversation (step 7); B-Plans (step 8); journeys (step 9).
"""

import datetime as dt
import logging
from functools import cache

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send

from out_of_frame import geocoding, grounding, investigation, map_objects, report
from out_of_frame.config import INVESTIGATIONS_AT_ONCE
from out_of_frame.investigation import Context
from out_of_frame.record import Record
from out_of_frame.state import Address, MapObject, RunState
from out_of_frame.web_search import WebSearch

log = logging.getLogger(__name__)


class ObjectToInvestigate(Record):
    """What one investigation gets from the run: its own input, not the run state, so that
    investigations can run in parallel."""

    map_object: MapObject


class UnclearAddressError(Exception):
    """The address has no single precise match in Berlin. TODO: in step 7, the agent asks the
    user instead."""


def run(address: str, date: dt.date, web_search: WebSearch) -> RunState:
    end = build_graph().invoke(
        RunState(property=Address(text=address)), context=Context(date, web_search)
    )
    return RunState.model_validate(end)


@cache
def build_graph():
    if INVESTIGATIONS_AT_ONCE < 2:  # a stream with its subgraphs takes one, see config.py
        raise ValueError("OUT_OF_FRAME_INVESTIGATIONS_AT_ONCE must be at least 2")
    builder = StateGraph(RunState, context_schema=Context)
    builder.add_node(geocode_property)
    builder.add_node(get_map_objects)
    builder.add_node(get_addresses)
    builder.add_node(investigate_object)
    builder.add_node(write_report)
    builder.add_node(fill_references)
    builder.add_edge(START, "geocode_property")
    builder.add_edge("geocode_property", "get_map_objects")
    builder.add_edge("get_map_objects", "get_addresses")
    builder.add_conditional_edges(
        "get_addresses", send_each_object_to_investigation, ["investigate_object", "write_report"]
    )
    builder.add_edge("investigate_object", "write_report")  # once every investigation has ended
    builder.add_edge("write_report", "fill_references")
    builder.add_edge("fill_references", END)
    return builder.compile().with_config(max_concurrency=INVESTIGATIONS_AT_ONCE)


def geocode_property(state: RunState) -> dict:
    coordinates = geocoding.geocode(state.property.text)
    if coordinates is None:
        raise UnclearAddressError(state.property.text)
    return {"property": state.property.model_copy(update={"coordinates": coordinates})}


def get_map_objects(state: RunState) -> dict:
    """The nearest map objects of each category around the property. If Overpass fails, the
    map part of the report is missing."""
    assert state.property.coordinates is not None  # geocode_property comes first
    try:
        found, source = map_objects.fetch_map_objects(state.property.coordinates)
    except map_objects.MapError as error:
        log.warning("the map failed: %s", error)
        return {"failures": ["map"]}
    return {"map_objects": found, "sources": [source]}


def get_addresses(state: RunState) -> dict:
    """The addresses of the objects to investigate, from one query, in place of the objects
    without them. If Overpass fails, they are investigated without addresses: the map part of
    the report stays."""
    chosen = choose_objects_to_investigate(state)
    try:
        addresses = map_objects.fetch_addresses(chosen)
    except map_objects.MapError as error:
        log.warning("the addresses failed, so the objects are investigated without them: %s", error)
        return {}
    found = [
        o.model_copy(update={"addresses": addresses[o.id]}) for o in chosen if o.id in addresses
    ]
    return {"map_objects": found}


def choose_objects_to_investigate(state: RunState) -> list[MapObject]:
    """Every object that code sends to investigation, and has no finding yet, nearest first:
    at most five per category, as the map keeps no more. TODO: in step 6.3, also the objects
    that triage cannot settle."""
    settled = {finding.map_object_id for finding in state.findings}
    chosen = [o for o in state.map_objects if is_sent_by_code(o) and o.id not in settled]
    return sorted(chosen, key=lambda o: o.distance_from_property_m)  # nearest first


def is_sent_by_code(map_object: MapObject) -> bool:
    """Every industrial object goes to investigation, even with a name and complete tags, and
    so does any object that is proposed or under construction; triage checks the others."""
    tags = map_object.details
    return tags["category"] == "industry" or map_objects.find_stage(tags) != "built"


def send_each_object_to_investigation(state: RunState) -> list[Send] | str:
    chosen = choose_objects_to_investigate(state)
    if not chosen:
        return "write_report"
    return [Send("investigate_object", ObjectToInvestigate(map_object=o)) for o in chosen]


def investigate_object(state: ObjectToInvestigate, runtime: Runtime[Context]) -> dict:
    """The investigation of one object; its finding, the page the finding cites, and a web
    search failure go into the run state. Each investigation numbers its pages from web-1, so
    in the run state a page's ID also names its object, such as osm-way-1/web-1."""
    context = runtime.context
    end = investigation.investigate(state.map_object, context.date, context.web_search)
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
