"""The report: one model call writes it from the run state, and code fills in its references,
see docs/architecture.md#grounding."""

import datetime as dt
import re
from functools import cache

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from out_of_frame import research_scope
from out_of_frame.config import MAP_OBJECTS_PER_CATEGORY, MODEL, REPORT_ATTEMPTS
from out_of_frame.finding import render
from out_of_frame.state import RunState, Source

CITATION = re.compile(r"\[([^\[\]\s]+)\]")  # [osm-way-1]
BRACKETS = re.compile(r"\[([^\[\]]*)\]")  # any [...]
LINK = re.compile(r"\]\(|\]:|(?:https?://|www\.)\S*")  # a Markdown link, or a URL of any form
OSM_CREDIT = "Map data © OpenStreetMap contributors: https://www.openstreetmap.org/copyright"
SCOPE_NOTE = f"The report covers the nearest {MAP_OBJECTS_PER_CATEGORY} objects of each kind."


class ReportError(Exception):
    """Every draft had a citation that is not one of the IDs the model was given. The model
    failed, so the run stops, see docs/architecture.md#failures."""


def write_report(state: RunState, date: dt.date) -> str:
    """The model's draft of the report, which cites objects by their IDs; fill_references then
    turns it into the report a person reads. A draft with a wrong citation is written again,
    and the model is told which citations were wrong."""
    scope = research_scope.load()
    system = SystemMessage(
        render("report.md.j2", date=date.isoformat(), types=scope.identified_types)
    )
    findings = {finding.map_object_id: finding for finding in state.findings}
    known = {map_object.id for map_object in state.map_objects}
    wrong: list[str] = []
    for _ in range(REPORT_ATTEMPTS):
        task = render(
            "report_task.md.j2",
            map_objects=state.map_objects,
            findings=findings,
            failures=state.failures,
            wrong_citations=wrong,
        )
        draft = build_report_model().invoke([system, HumanMessage(task)]).text
        wrong = find_wrong_citations(draft, known)
        if not wrong:
            return draft
    raise ReportError(f"{REPORT_ATTEMPTS} drafts had wrong citations, last: {', '.join(wrong)}")


def find_wrong_citations(draft: str, known: set[str]) -> list[str]:
    """Each bracket in the draft that is not one known ID, such as several IDs in one bracket
    or an unknown ID, and each bracket left without its pair, as in [[osm-way-1]]; each known
    ID in the text, outside a citation, since the reader does not know the IDs; and each link
    or URL: code adds the sources, so a URL in the draft would be made up."""
    brackets = [match[0] for match in BRACKETS.finditer(draft) if match[1] not in known]
    text = BRACKETS.sub(" ", draft)
    unpaired = [bracket for bracket in "[]" if bracket in text]
    # A whole ID, also in Markdown emphasis such as _osm-way-1_, but not the start of osm-way-10.
    in_text = [
        id
        for id in sorted(known)
        if re.search(rf"(?<![^\W_])(?<!-){re.escape(id)}(?![^\W_])(?!-)", text)
    ]
    return sorted(brackets + unpaired + in_text + LINK.findall(draft))


@cache
def build_report_model():
    return ChatAnthropic(model=MODEL)


def fill_references(draft: str, state: RunState) -> str:
    """The report a person reads: a title, the draft with each cited object ID replaced by the
    numbers of its sources, then the sources and the map credit. A web page is given by its
    URL, map data by its name. An object cites the page of its finding and its own map data,
    since the report also gives facts from the map, such as its address."""
    objects = {map_object.id: map_object for map_object in state.map_objects}
    evidence = {finding.map_object_id: finding.evidence_id for finding in state.findings}
    sources = {source.id: source for source in state.sources}
    numbers: dict[str, int] = {}  # by the source as the person reads it

    def cite(match: re.Match) -> str:
        map_object = objects[match[1]]
        ids = [id for id in [evidence.get(map_object.id), map_object.source_id] if id]
        cited = {numbers.setdefault(name_source(sources[id]), len(numbers) + 1) for id in ids}
        return "[" + ", ".join(str(number) for number in sorted(cited)) + "]"

    text = CITATION.sub(cite, draft).strip()
    lines = [f"# What lies around {state.property.text}", "", text, "", SCOPE_NOTE, ""]
    if numbers:
        lines += ["Sources:", *(f"{n}. {name}" for name, n in numbers.items()), ""]
    return "\n".join([*lines, OSM_CREDIT])


def name_source(source: Source) -> str:
    return source.url if source.kind == "web search" else "OpenStreetMap"
