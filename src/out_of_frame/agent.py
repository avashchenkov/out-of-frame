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
    builder = StateGraph(RunState, context_schema=Context)
    builder.add_node(geocode_property)
    builder.add_node(get_map_objects)
    builder.add_node(investigate_object)
    builder.add_node(write_report)
    builder.add_node(fill_references)
    builder.add_edge(START, "geocode_property")
    builder.add_edge("geocode_property", "get_map_objects")
    builder.add_conditional_edges(
        "get_map_objects", send_each_object_to_investigation, ["investigate_object", "write_report"]
    )
    builder.add_edge("investigate_object", "write_report")  # once every investigation has ended
    builder.add_edge("write_report", "fill_references")
    builder.add_edge("fill_references", END)
    return builder.compile()


def geocode_property(state: RunState) -> dict:
    coordinates = geocoding.geocode(state.property.text)
    if coordinates is None:
        raise UnclearAddressError(state.property.text)
    return {"property": state.property.model_copy(update={"coordinates": coordinates})}


def get_map_objects(state: RunState) -> dict:
    """The map objects around the property. Until step 6, only the one that is investigated is
    kept, with its addresses. If Overpass fails, the map part of the report is missing."""
    assert state.property.coordinates is not None  # geocode_property comes first
    try:
        found, source = map_objects.fetch_map_objects(state.property.coordinates)
        chosen = choose_object_to_investigate(found)
        if chosen is None:
            return {"sources": [source]}
        addresses = map_objects.fetch_addresses(chosen)
    except map_objects.MapError as error:
        log.warning("the map failed: %s", error)
        return {"failures": ["map"]}
    chosen = chosen.model_copy(update={"addresses": addresses})
    return {"map_objects": [chosen], "sources": [source]}


def choose_object_to_investigate(found: list[MapObject]) -> MapObject | None:
    """The nearest unnamed industrial object. TODO: in step 6, code routing and triage choose
    the objects, up to five per category."""
    unnamed = [o for o in found if o.name is None and o.details["category"] == "industry"]
    return min(unnamed, key=lambda o: o.distance_from_property_m, default=None)


def send_each_object_to_investigation(state: RunState) -> list[Send] | str:
    if not state.map_objects:
        return "write_report"
    return [
        Send("investigate_object", ObjectToInvestigate(map_object=o)) for o in state.map_objects
    ]


def investigate_object(state: ObjectToInvestigate, runtime: Runtime[Context]) -> dict:
    """The investigation of one object; its finding, the page the finding cites, and a web
    search failure go into the run state. TODO: in step 6, give pages IDs that stay unique
    across parallel investigations."""
    context = runtime.context
    end = investigation.investigate(state.map_object, context.date, context.web_search)
    assert end.finding is not None  # every path through the subgraph ends with a finding
    cited = grounding.collect_cited_page(end.finding.evidence_id, end.pages)
    return {
        "findings": [end.finding],
        "sources": cited,
        "failures": ["web search"] if end.web_search_failed else [],
    }


def write_report(state: RunState, runtime: Runtime[Context]) -> dict:
    """The model's draft, which the evals grade before code fills in its references."""
    return {"report": report.write_report(state, runtime.context.date)}


def fill_references(state: RunState) -> dict:
    assert state.report is not None  # write_report comes first
    return {"report": report.fill_references(state.report, state)}
