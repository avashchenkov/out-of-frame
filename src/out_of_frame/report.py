"""The report: one model call writes it from the run state, and code fills in its references,
see docs/architecture.md#grounding, and adds its own texts, in the user's language."""

import datetime as dt
import logging
import re
import string
from functools import cache
from urllib.parse import urlsplit

import anthropic
from langchain_core.messages import HumanMessage, SystemMessage

from out_of_frame import research_scope, transit
from out_of_frame.chat_model import build_chat_model
from out_of_frame.config import MAP_OBJECTS_PER_CATEGORY, PLANS, REPORT_ATTEMPTS
from out_of_frame.finding import render
from out_of_frame.record import Record
from out_of_frame.state import Journey, MapObject, RunState, Service, Source

log = logging.getLogger(__name__)

CITATION = re.compile(r"\[([^\[\]\s]+)\]")  # [osm-way-1]
CITATIONS = re.compile(r"\[[^\[\]\s]+\](?:[ \t]*\[[^\[\]\s]+\])*")  # [osm-way-1][osm-way-2]
BRACKETS = re.compile(r"\[([^\[\]]*)\]")  # any [...]
LINK = re.compile(r"\]\(|\]:|(?:https?://|www\.)\S*")  # a Markdown link, or a URL of any form
# The credits that the licences require, word for word, so they are never translated.
OSM_CREDIT = "Map data © OpenStreetMap contributors: https://www.openstreetmap.org/copyright"
TRANSITOUS_CREDIT = (
    "Journeys planned with Transitous and its sources: https://transitous.org/sources/"
)
# The fields in which the B-Plan WFS links a plan's own documents, the most useful first: the
# plan's drawing, the page of its procedure and the page of its public display.
PLAN_DOCUMENTS = ["scan_www", "url_www", "ausleg_www"]


class ReportError(Exception):
    """Every draft had a citation that is not one of the IDs the model was given, or left out
    an object. The model failed, so the run stops, see docs/architecture.md#failures."""


class ReportTexts(Record):
    """The texts that code adds to the report, in English or in the user's language. Code fills
    in each placeholder, such as {address}, so no value of the run, such as the address, a time
    or a link, passes through a translation."""

    title: str
    language_model_note: str
    journeys_heading: str
    journeys_intro: str
    journey: str
    minutes: str
    no_route: str
    unavailable: str
    about_heading: str
    scope: str
    kinds: str
    licences_heading: str
    map_link: str
    plan_link: str


@cache
def write_english_texts() -> ReportTexts:
    """The texts in English, with the kinds of objects that the report covers from the research
    scope."""
    categories = [c for c in research_scope.load().categories if c.source == "overpass"]
    return ReportTexts(
        title="What lies around {address}",
        language_model_note="A language model wrote this report, and it can be wrong: check "
        "what matters to you against the sources.",
        journeys_heading="Journeys",
        journeys_intro="Journeys by public transport on a normal weekday. Each time is the mean "
        "travel time of up to {connections} connections that leave at the given time or later, "
        "without the wait for them:",
        journey="{destination}: there, leaving home at {leave_home} or later, {there}; back "
        "home, leaving it at {leave_place} or later, {back}.",
        minutes="{minutes} min",
        no_route="no connection found",
        unavailable="not known, as the journey planner failed",
        about_heading="About this report",
        # What a development plan is, so that the model never has to say it and no judge
        # grades it.
        scope="The report covers the nearest {objects} objects of each kind it checks: {kinds}; "
        "and the nearest {plans} development plans in force or in procedure. A development "
        "plan, or Bebauungsplan, sets the legal rules for what may be built in its area; one "
        "still in procedure is only a draft of them.",
        kinds="; ".join(c.name[0].lower() + c.name[1:] for c in categories),
        licences_heading="Licences",
        map_link="map",
        plan_link="plan document",
    )


def translate_texts(language: str) -> ReportTexts:
    """The texts that code adds to the report, in the language: the model translates them from
    English. They all stay in English if one translation does not fit, see fits, or if the
    answer fails, is cut off or does not parse: the report still comes out, with these texts in
    one language or the other."""
    english = write_english_texts()
    if language == "English":
        return english
    prompt = render("translate.md.j2", language=language, texts=english.model_dump_json(indent=2))
    try:
        answer = build_translation_model().invoke([HumanMessage(prompt)])
    except anthropic.APIError as error:
        log.warning("the texts were not translated: %s", error)
        return english
    stop_reason = answer["raw"].response_metadata.get("stop_reason")
    if stop_reason != "end_turn" or answer["parsing_error"] or answer["parsed"] is None:
        log.warning("the texts were not translated: stop reason %s", stop_reason)
        return english
    translated = answer["parsed"]
    unfit = [
        name
        for name, text in english.model_dump().items()
        if not fits(getattr(translated, name), text)
    ]
    if unfit:
        log.warning("the texts stay in English, as these do not fit: %s", ", ".join(unfit))
        return english
    return translated


def fits(translation: str, text: str) -> bool:
    """Whether code can fill in the translation in place of the text: it is not empty and has
    the same placeholders, such as {address}, in the same order, so that no two values change
    places, such as the times there and back, and without a format or a conversion, such as
    {minutes:s}, which the English texts never have and which could fail when code fills them
    in."""
    try:
        same = find_placeholders(translation) == find_placeholders(text)
    except ValueError:  # a curly bracket without its pair
        return False
    return same and bool(translation.strip())


def find_placeholders(text: str) -> list[tuple[str, str, str]]:
    """Each placeholder in the text, in order, as its name, format and conversion."""
    fields = string.Formatter().parse(text)
    return [
        (name, spec or "", conversion or "")
        for _, name, spec, conversion in fields
        if name is not None
    ]


@cache
def build_translation_model():
    """The model with native structured output, as in conversation.build_extract_model."""
    return build_chat_model().with_structured_output(
        ReportTexts, method="json_schema", include_raw=True
    )


def write_report(state: RunState, date: dt.date) -> str:
    """The model's draft of the report, which cites objects by their IDs; fill_references then
    turns it into the report a person reads. A draft with a wrong citation, or one that leaves
    out an object, is written again, and the model is told what was wrong."""
    scope = research_scope.load()
    system = SystemMessage(
        render(
            "report.md.j2",
            date=date.isoformat(),
            types=scope.identified_types,
            language=state.find_language(),
        )
    )
    findings = {finding.map_object_id: finding for finding in state.findings}
    known = {map_object.id for map_object in state.map_objects}
    plans = find_plans(state)
    wrong: list[str] = []
    missing: list[str] = []
    for _ in range(REPORT_ATTEMPTS):
        task = render(
            "report_task.md.j2",
            map_objects=state.map_objects,
            findings=findings,
            failures=find_reported_failures(state),
            plans=plans,
            wrong_citations=wrong,
            missing_objects=missing,
        )
        draft = build_report_model().invoke([system, HumanMessage(task)]).text
        wrong = find_wrong_citations(draft, known)
        missing = sorted(known - set(CITATION.findall(draft)))
        if not wrong and not missing:
            return draft
    raise ReportError(
        f"{REPORT_ATTEMPTS} drafts had wrong citations or left out objects, last: "
        + ", ".join(wrong + missing)
    )


def find_plans(state: RunState) -> set[str]:
    """The IDs of the objects that are development plans, not map objects."""
    return {o.id for o in state.map_objects if state.find_source_kind(o) == "plans"}


def find_reported_failures(state: RunState) -> list[Service]:
    """The failed services whose part of the report the model writes. Code writes the journeys,
    so the model has nothing to say about a transit failure."""
    return [service for service in state.failures if service != "transit"]


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
    """The model, with room for its thinking and the report: see MAX_TOKENS in config.py."""
    return build_chat_model()


def fill_references(draft: str, state: RunState, texts: ReportTexts | None = None) -> str:
    """The report a person reads, in Markdown: a title, a note that a language model wrote it,
    the draft, which the model writes in sections, with each citation replaced by links to its
    sources, the journeys, what the report covers, then the licences. Citations in a row, such
    as [osm-way-1][osm-way-2], become one. An object cites the page of its finding and its own
    map or plan data, since the report also gives facts from that data, such as its name. The
    texts that code adds are in English unless translated ones are given."""
    texts = texts or write_english_texts()
    objects = {map_object.id: map_object for map_object in state.map_objects}
    evidence = {finding.map_object_id: finding.evidence_id for finding in state.findings}
    sources = {source.id: source for source in state.sources}

    def cite(match: re.Match) -> str:
        links: dict[str, list[str]] = {}  # the URLs under each name, none for a source without
        for object_id in CITATION.findall(match[0]):
            map_object = objects[object_id]
            for id in [evidence.get(map_object.id), map_object.source_id]:
                if id:
                    name, url = link_source(sources[id], map_object, texts)
                    urls = links.setdefault(name, [])
                    if url and url not in urls:
                        urls.append(url)
        return f"({write_links(links)})"

    text = CITATIONS.sub(cite, draft).strip()
    assert state.property is not None  # research starts only once the property is resolved
    title = texts.title.format(address=state.property.text)
    lines = [f"# {title}", "", texts.language_model_note, "", text, ""]
    lines += [*describe_journeys(state, texts), f"## {texts.about_heading}", ""]
    lines += [describe_scope(texts), ""]
    credits = [OSM_CREDIT, TRANSITOUS_CREDIT] if state.journeys else [OSM_CREDIT]
    return "\n".join([*lines, f"## {texts.licences_heading}", "", *(f"- {c}" for c in credits)])


def describe_journeys(state: RunState, texts: ReportTexts) -> list[str]:
    """The journeys as lines of the report, under their heading, one line per destination with
    both directions, or none if the user travels nowhere. They are plain data, so code writes
    them, not the model."""
    if not state.journeys:
        return []
    intro = texts.journeys_intro.format(connections=transit.CONNECTIONS)
    lines = [f"## {texts.journeys_heading}", "", intro, ""]
    for destination in state.destinations or []:
        journeys = {j.direction: j for j in state.journeys if j.destination_id == destination.id}
        leave_home, leave_place = destination.leave_home, destination.leave_place
        assert leave_home is not None and leave_place is not None  # see conversation.find_missing
        line = texts.journey.format(
            destination=destination.name,
            leave_home=f"{leave_home:%H:%M}",
            there=describe_journey(journeys["there"], texts),
            leave_place=f"{leave_place:%H:%M}",
            back=describe_journey(journeys["back"], texts),
        )
        lines.append(f"- {line}")
    return [*lines, ""]


def describe_journey(journey: Journey, texts: ReportTexts) -> str:
    """How long the journey takes, in whole minutes, or why that is not known."""
    match journey.outcome:
        case "found":
            assert journey.mean_duration is not None  # a found journey has one, see transit.py
            return texts.minutes.format(minutes=round(journey.mean_duration.total_seconds() / 60))
        case "no route":
            return texts.no_route
        case "unavailable":
            return texts.unavailable


def describe_scope(texts: ReportTexts) -> str:
    """Which kinds of objects the report covers, from the research scope, and what a
    development plan is."""
    return texts.scope.format(objects=MAP_OBJECTS_PER_CATEGORY, kinds=texts.kinds, plans=PLANS)


def link_source(
    source: Source, map_object: MapObject, texts: ReportTexts
) -> tuple[str, str | None]:
    """The name and URL of one of the object's sources, as a person opens it: a web page by its
    site's name, the map data by the object's own page on OpenStreetMap, and the plan data by
    the plan's own document. A plan for which the WFS links no document is named, not linked."""
    if source.kind == "web search":
        site = (urlsplit(source.url).hostname or source.url).removeprefix("www.")
        return site, escape_url(source.url)
    if source.kind == "map":
        kind, number = map_object.id.removeprefix("osm-").split("-")  # see map_objects.py
        return texts.map_link, f"https://www.openstreetmap.org/{kind}/{number}"
    assert source.kind == "plans"  # an object comes from the map or the plans
    fields = [map_object.details.get(field, "").strip() for field in PLAN_DOCUMENTS]
    url = next((url for url in fields if url.startswith(("https://", "http://"))), None)
    return (texts.plan_link, escape_url(url)) if url else ("Berlin B-Plan WFS", None)


def write_links(links: dict[str, list[str]]) -> str:
    """The links of one citation: the name as the link for one URL, the name and numbered links
    for several, such as the map pages of three railway lines, and the name alone without."""
    parts = []
    for name, urls in links.items():
        if len(urls) > 1:
            parts.append(f"{name}: " + ", ".join(f"[{n}]({url})" for n, url in enumerate(urls, 1)))
        else:
            parts.append(f"[{name}]({urls[0]})" if urls else name)
    return ("; " if any(len(urls) > 1 for urls in links.values()) else ", ").join(parts)


def escape_url(url: str) -> str:
    """The URL with its spaces and brackets encoded, so that it cannot end a Markdown link."""
    return url.replace(" ", "%20").replace("(", "%28").replace(")", "%29")
