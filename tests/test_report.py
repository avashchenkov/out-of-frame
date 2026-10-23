"""The report with a stubbed model: what the model gets, and how code fills in the references."""

import datetime as dt
import re

import anthropic
import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from out_of_frame import report
from out_of_frame.config import REPORT_ATTEMPTS
from out_of_frame.report import ReportError, fill_references, write_report
from out_of_frame.state import (
    Address,
    Coordinates,
    Destination,
    Finding,
    Journey,
    MapObject,
    RunState,
    Source,
)

DATE = dt.date(2026, 10, 10)
SITE = MapObject(
    id="osm-way-1",
    name=None,
    details={"landuse": "industrial", "category": "industry"},
    addresses=["Teststraße 1, 13597 Berlin"],
    coordinates=Coordinates(lat=52.5, lon=13.4),
    distance_from_property_m=118,
    source_id="overpass-1",
)
MAP = Source(id="overpass-1", kind="map", request="[out:json];", url="https://overpass", content="")
PAGE = Source(
    id="web-1",
    kind="web search",
    request="Teststraße 1 Berlin",
    url="https://example.org/test-gmbh",
    content="Test GmbH makes parts at Teststraße 1.",
)
FOUND = Finding(
    map_object_id="osm-way-1",
    outcome="identified",
    identified_type="production",
    status=None,
    key_facts=["Test GmbH makes parts"],
    evidence_id="web-1",
)
STATE = RunState(
    property=Address(text="Freiheit 22, 13597 Berlin"),
    sources=[MAP, PAGE],
    map_objects=[SITE],
    findings=[FOUND],
)
OSM = "https://www.openstreetmap.org/way"
ENGLISH = report.write_english_texts()
SITE_LINKS = f"([example.org](https://example.org/test-gmbh), [map]({OSM}/1))"


class FakeWriter:
    """Answers with the given drafts in turn, or, by default, cites every object it is given;
    keeps every request."""

    def __init__(self, *drafts: str):
        self.drafts = list(drafts)
        self.requests = []

    def invoke(self, request):
        self.requests.append(request)
        if self.drafts:
            return AIMessage(self.drafts.pop(0))
        ids = re.findall(r"^\[(\S+)\] An object", request[-1].content, re.MULTILINE)
        return AIMessage(" ".join(f"An object [{id}]." for id in ids) or "No object is listed.")


def write(monkeypatch, state=STATE, *drafts):
    """The report a person reads, from the draft the model writes."""
    writer = FakeWriter(*drafts)
    monkeypatch.setattr(report, "build_report_model", lambda: writer)
    return fill_references(write_report(state, DATE), state), writer


def with_a_plan() -> RunState:
    """STATE with a development plan, bplan-2, and a map object, osm-way-3, that have the same
    data: only their sources tell them apart."""
    plans = Source(id="bplan-wfs-1", kind="plans", request="", url="", content="")
    fields = {"planname": "VIII-B6", "bp_rechtsstand": "In Kraft getreten", "category": "industry"}
    plan = SITE.model_copy(update={"id": "bplan-2", "details": fields, "source_id": plans.id})
    site = SITE.model_copy(update={"id": "osm-way-3", "details": fields})
    return STATE.model_copy(
        update={"sources": [*STATE.sources, plans], "map_objects": [plan, site], "findings": []}
    )


def test_a_plan_is_marked_by_its_source_alone(monkeypatch):
    _, writer = write(monkeypatch, with_a_plan())
    system, task = writer.requests[0]
    assert (
        "[bplan-2] An object 118 m from the property, a development plan. Its map" in task.content
    )
    assert "[osm-way-3] An object 118 m from the property. Its map" in task.content
    assert "unknown whether building has started" in system.content
    rules = " ".join(system.content.split())
    assert "for a plan still in the planning procedure, what it is meant to allow" in rules
    assert "never that its type shows no effect or that it is harmless" in rules
    assert "the land at that distance has a development plan" in rules


def test_the_model_gets_whole_metres_and_reads_0_m_by_its_rules(monkeypatch):
    near = SITE.model_copy(update={"distance_from_property_m": 0.4})
    far = SITE.model_copy(update={"id": "osm-way-2", "distance_from_property_m": 117.6})
    _, writer = write(monkeypatch, STATE.model_copy(update={"map_objects": [near, far]}))
    [[system, task]] = writer.requests
    assert "[osm-way-1] An object 0 m from the property. Its map" in task.content
    assert "[osm-way-2] An object 118 m from the property. Its map" in task.content
    rule = "A distance of 0 m means that the property lies in the object's area or right next to it"
    assert rule in " ".join(system.content.split())


def test_code_says_what_a_development_plan_is(monkeypatch):
    text, _ = write(monkeypatch)
    assert "A development plan, or Bebauungsplan, sets the legal rules" in text


def test_the_model_writes_a_draft_that_cites_object_ids(monkeypatch):
    monkeypatch.setattr(report, "build_report_model", lambda: FakeWriter("A site [osm-way-1]."))
    assert write_report(STATE, DATE) == "A site [osm-way-1]."


def test_a_citation_becomes_links_to_the_page_and_to_the_object_on_the_map(monkeypatch):
    text, _ = write(monkeypatch, STATE, "A workshop 118 m away makes parts [osm-way-1].")
    assert text.startswith("# What lies around Freiheit 22, 13597 Berlin\n")
    assert f"makes parts {SITE_LINKS}." in text
    assert "Sources" not in text and text.endswith(report.OSM_CREDIT)


def test_a_page_is_named_by_its_site_and_its_url_cannot_end_the_link(monkeypatch):
    page = PAGE.model_copy(update={"url": "https://www.example.org/Test (GmbH)"})
    text, _ = write(
        monkeypatch, STATE.model_copy(update={"sources": [MAP, page]}), "A [osm-way-1]."
    )
    assert "([example.org](https://www.example.org/Test%20%28GmbH%29), [map]" in text


@pytest.mark.parametrize(
    "fields, links",
    [
        (
            {"scan_www": "https://plans.example/8-1.pdf", "url_www": "https://example.org/8-1"},
            "([plan document](https://plans.example/8-1.pdf))",
        ),
        (
            {"scan_www": "", "url_www": "https://example.org/8-1"},
            "([plan document](https://example.org/8-1))",
        ),
        ({"scan_www": "not a link"}, "(Berlin B-Plan WFS)"),
    ],
    ids=["its drawing", "its procedure", "no document"],
)
def test_a_plan_cites_its_own_document(monkeypatch, fields, links):
    state = with_a_plan()
    plan = state.map_objects[0].model_copy(update={"details": fields})
    state = state.model_copy(update={"map_objects": [plan]})
    text, _ = write(monkeypatch, state, "A plan [bplan-2].")
    assert f"A plan {links}." in text


def test_a_finding_that_cites_the_map_names_it_once(monkeypatch):
    from_the_map = FOUND.model_copy(update={"evidence_id": "overpass-1"})
    state = STATE.model_copy(update={"findings": [from_the_map]})
    text, _ = write(monkeypatch, state, "A workshop [osm-way-1].")
    assert f"A workshop ([map]({OSM}/1))." in text


def test_an_unidentified_object_cites_its_map_data(monkeypatch):
    state = STATE.model_copy(update={"findings": [Finding.unidentified("osm-way-1")]})
    text, _ = write(monkeypatch, state, "An unidentified industrial area [osm-way-1].")
    assert f"industrial area ([map]({OSM}/1))." in text


def test_the_model_gets_the_map_data_without_the_category_and_the_failures(monkeypatch):
    state = STATE.model_copy(update={"failures": ["web search"]})
    _, writer = write(monkeypatch, state)
    [[system, task]] = writer.requests
    assert "2026-10-10" in system.content and "- production:" in system.content
    assert "[osm-way-1] An object 118 m from the property" in task.content
    assert "landuse=industrial" in task.content and "category" not in task.content
    assert "Finding: production, status not given. Key facts: Test GmbH makes parts" in task.content
    assert "failed after their retries, so their part of the report is missing: web search." in (
        task.content
    )


def test_an_object_that_was_not_investigated_is_marked_and_cites_its_map_data(monkeypatch):
    state = STATE.model_copy(update={"findings": []})
    text, writer = write(monkeypatch, state, "A site, not investigated [osm-way-1].")
    assert "Finding: not investigated." in writer.requests[0][-1].content
    assert f"not investigated ([map]({OSM}/1))." in text


@pytest.mark.parametrize(
    "citation, told",
    [
        ("[osm-way-9]", "[osm-way-9]"),
        ("[osm-way-1, osm-way-9]", "[osm-way-1, osm-way-9]"),
        ("[osm-way-1](https://made-up.example)", "https://made-up.example)"),
        ("[[osm-way-1]](https://made-up.example)", "]("),
        ("[osm-way-1]\n\n[osm-way-1]: https://made-up.example", "]:"),
        ("(see www.made-up.example)", "www.made-up.example)"),
        ("[here]", "[here]"),
        ("at osm-way-1 [osm-way-1]", "osm-way-1"),
    ],
    ids=[
        "unknown",
        "two in one",
        "a link",
        "a link around",
        "a link definition",
        "a url",
        "not an id",
        "an id in the text",
    ],
)
def test_a_draft_with_a_wrong_citation_is_written_again(monkeypatch, citation, told):
    text, writer = write(monkeypatch, STATE, f"A site {citation}.", "A site [osm-way-1].")
    assert f"A site {SITE_LINKS}." in text and "made-up" not in text
    assert told in writer.requests[1][-1].content


def test_wrong_citations_in_every_draft_stop_the_run(monkeypatch):
    drafts = ["A site [osm-way-9]."] * REPORT_ATTEMPTS
    with pytest.raises(ReportError):
        write(monkeypatch, STATE, *drafts)


def test_with_no_objects_the_report_has_no_links(monkeypatch):
    state = RunState(property=Address(text="Freiheit 22, 13597 Berlin"))
    text, writer = write(monkeypatch, state)
    assert "No object of the checked kinds was found" in writer.requests[0][-1].content
    assert "](" not in text and text.endswith(report.OSM_CREDIT)


def journey(id: str, direction, outcome, minutes: float | None = None) -> Journey:
    duration = None if minutes is None else dt.timedelta(minutes=minutes)
    return Journey(destination_id=id, direction=direction, outcome=outcome, mean_duration=duration)


def test_code_adds_each_journey_with_its_destination_direction_and_duration(monkeypatch):
    def destination(id: str, name: str, leave_home: dt.time, leave_place: dt.time) -> Destination:
        address = Address(text=f"{name} 1", coordinates=Coordinates(lat=52.5, lon=13.4))
        return Destination(
            id=id, name=name, address=address, leave_home=leave_home, leave_place=leave_place
        )

    state = STATE.model_copy(
        update={
            "destinations": [
                destination("destination-1", "work", dt.time(7, 40), dt.time(18, 10)),
                destination("destination-2", "the gym", dt.time(19), dt.time(21, 5)),
            ],
            "journeys": [
                journey("destination-2", "back", "unavailable"),
                journey("destination-1", "there", "found", 50.4),
                journey("destination-2", "there", "no route"),
                journey("destination-1", "back", "found", 47.5),
            ],
            "failures": ["transit"],
        }
    )
    text, writer = write(monkeypatch, state)
    assert "transit" not in writer.requests[0][-1].content  # the model does not write them
    assert (
        "## Journeys\n\n"
        "Journeys by public transport on a normal weekday. Each time is the mean travel time of "
        "up to 3 connections that leave at the given time or later, without the wait for them:"
        "\n\n"
        "- work: there, leaving home at 07:40 or later, 50 min; back home, leaving it at 18:10 "
        "or later, 48 min.\n"
        "- the gym: there, leaving home at 19:00 or later, no connection found; back home, "
        "leaving it at 21:05 or later, not known, as the journey planner failed.\n\n"
        "## About this report\n\nThe report covers"
    ) in text
    assert text.endswith(f"- {report.OSM_CREDIT}\n- {report.TRANSITOUS_CREDIT}")


def test_without_journeys_the_report_has_no_journeys_and_no_transit_credit(monkeypatch):
    text, _ = write(monkeypatch, STATE.model_copy(update={"destinations": []}))
    assert "Journeys" not in text and "transitous" not in text
    assert text.endswith(report.OSM_CREDIT)


@pytest.mark.parametrize("service", ["map", "plans"])
def test_a_source_failure_is_not_told_as_nothing_found(monkeypatch, service):
    state = RunState(property=Address(text="Freiheit 22, 13597 Berlin"), failures=[service])
    _, writer = write(monkeypatch, state)
    task = writer.requests[0][-1].content
    assert "was found" not in task
    assert f"so their part of the report is missing: {service}." in task


@pytest.mark.parametrize(
    "draft",
    ["The object osm-way-1 [osm-way-1].", "The object _osm-way-1_ [osm-way-1].", "__osm-way-1__"],
)
def test_an_id_in_the_text_is_told(draft):
    assert report.find_wrong_citations(draft, {"osm-way-1"}) == ["osm-way-1"]


def test_a_longer_id_in_the_text_is_not_a_known_one():
    assert report.find_wrong_citations("A site [osm-way-1], not osm-way-10.", {"osm-way-1"}) == []


@pytest.mark.parametrize("draft", ["A site [[osm-way-1]].", "A site [osm-way-1]]."])
def test_a_bracket_without_its_pair_is_told(draft):
    assert report.find_wrong_citations(draft, {"osm-way-1"})


RAILWAY = SITE.model_copy(
    update={"id": "osm-way-2", "details": {"railway": "rail", "category": "road_rail"}}
)
TRIAGED = Finding(
    map_object_id="osm-way-2",
    outcome="identified",
    identified_type="railway",
    status="operating",
    key_facts=["railway=rail"],
    evidence_id="overpass-1",
)
TWO = STATE.model_copy(update={"map_objects": [SITE, RAILWAY], "findings": [FOUND, TRIAGED]})


def test_a_draft_that_leaves_out_an_object_is_written_again(monkeypatch):
    first, second = "A site [osm-way-1].", "A site [osm-way-1]. A railway [osm-way-2]."
    text, writer = write(monkeypatch, TWO, first, second)
    assert "left out these objects" in writer.requests[1][-1].content
    assert "osm-way-2" in writer.requests[1][-1].content and f"A railway ([map]({OSM}/2))." in text


def test_a_draft_that_always_leaves_out_an_object_stops_the_run(monkeypatch):
    with pytest.raises(ReportError, match="osm-way-2"):
        write(monkeypatch, TWO, *["A site [osm-way-1]."] * REPORT_ATTEMPTS)


@pytest.mark.parametrize("between", ["", " "])
def test_citations_in_a_row_become_one(monkeypatch, between):
    text, _ = write(monkeypatch, TWO, f"A site and a railway [osm-way-1]{between}[osm-way-2].")
    links = f"([example.org](https://example.org/test-gmbh); map: [1]({OSM}/1), [2]({OSM}/2))"
    assert f"A site and a railway {links}." in text


def test_citations_in_two_paragraphs_stay_apart(monkeypatch):
    text, _ = write(monkeypatch, TWO, "A site [osm-way-1]\n\n[osm-way-2] A railway.")
    assert f"A site {SITE_LINKS}\n\n([map]({OSM}/2)) A railway." in text


def test_the_report_says_which_kinds_it_checks(monkeypatch):
    text, _ = write(monkeypatch, STATE, "A site [osm-way-1].")
    assert "nearest 5 objects of each kind it checks: industrial and energy sites;" in text


def test_the_report_says_that_a_language_model_wrote_it(monkeypatch):
    text, _ = write(monkeypatch)
    assert text.startswith(
        f"# What lies around Freiheit 22, 13597 Berlin\n\n{ENGLISH.language_model_note}\n\n"
    )


def test_the_model_writes_the_sections_of_the_report(monkeypatch):
    _, writer = write(monkeypatch)
    rules = " ".join(writer.requests[0][0].content.split())
    assert "Write the report in Markdown, in these sections, in this order" in rules
    assert 'heading of level 2 that means, in English: "Nearby"' in rules
    assert '"Development plans"' in rules
    assert '"Not identified", the objects that could not be identified' in rules


def test_code_adds_its_parts_around_the_sections_of_the_draft(monkeypatch):
    text, _ = write(monkeypatch, STATE, "## Nearby\n\nA workshop makes parts [osm-way-1].")
    assert (
        f"{ENGLISH.language_model_note}\n\n## Nearby\n\nA workshop makes parts {SITE_LINKS}.\n\n"
        "## About this report\n\nThe report covers"
    ) in text
    assert ".\n\n## Licences\n\n- " in text


def test_the_model_writes_the_report_in_the_users_language(monkeypatch):
    _, writer = write(monkeypatch, STATE.model_copy(update={"language": "German"}))
    rules = " ".join(writer.requests[0][0].content.split())
    assert "Write the whole report in German, its headings too" in rules
    assert "Keep names and addresses as they are" in rules
    _, writer = write(monkeypatch)
    assert "Write the whole report in English, its headings" in writer.requests[0][0].content


GERMAN = {
    "title": "Was liegt um {address}",
    "language_model_note": "Ein Sprachmodell hat diesen Bericht geschrieben.",
    "about_heading": "Über diesen Bericht",
    "scope": "Der Bericht nennt die {objects} nächsten Objekte jeder Art: {kinds}; und die "
    "{plans} nächsten Bebauungspläne.",
    "kinds": "Industrie",
    "licences_heading": "Lizenzen",
    "map_link": "Karte",
}


def stub_the_translation(monkeypatch, texts: dict, stop_reason="end_turn", parses=True) -> list:
    """The translation model answers with the English texts, the given ones changed, or with an
    answer that does not parse; returns the requests."""
    requests = []

    def reply(request):
        requests.append(request)
        raw = AIMessage("", response_metadata={"stop_reason": stop_reason})
        parsed = ENGLISH.model_copy(update=texts) if parses else None
        return {"raw": raw, "parsed": parsed, "parsing_error": None if parses else "not JSON"}

    monkeypatch.setattr(report, "build_translation_model", lambda: RunnableLambda(reply))
    return requests


def test_code_adds_its_texts_in_the_users_language_but_the_credits_word_for_word(monkeypatch):
    requests = stub_the_translation(monkeypatch, GERMAN)
    texts = report.translate_texts("German")
    text = fill_references("A workshop [osm-way-1].", STATE, texts)
    assert text == (
        "# Was liegt um Freiheit 22, 13597 Berlin\n\n"
        "Ein Sprachmodell hat diesen Bericht geschrieben.\n\n"
        f"A workshop ([example.org](https://example.org/test-gmbh), [Karte]({OSM}/1)).\n\n"
        "## Über diesen Bericht\n\n"
        "Der Bericht nennt die 5 nächsten Objekte jeder Art: Industrie; und die 5 nächsten "
        "Bebauungspläne.\n\n"
        f"## Lizenzen\n\n- {report.OSM_CREDIT}"
    )
    [[prompt]] = requests
    assert prompt.content.startswith("Translate the texts below into German.")
    assert '"title": "What lies around {address}"' in prompt.content


def test_english_texts_need_no_translation(monkeypatch):
    requests = stub_the_translation(monkeypatch, GERMAN)
    assert report.translate_texts("English") == ENGLISH and requests == []


@pytest.mark.parametrize(
    "field, translation",
    [
        ("title", "Was liegt hier"),
        ("title", "Was liegt um {adresse}"),
        ("title", "{address}: {address}"),
        ("title", "Was liegt um {address}}"),
        ("title", "Was liegt um {address:{missing}}"),
        ("minutes", "{minutes:s} Min."),
        ("title", "Was liegt um {address!r}"),
        ("minutes", "{minutes} Min. {minutes}"),
        (
            "journey",
            "{destination}: hin ab {leave_home}, {back}; zurück ab {leave_place}, {there}.",
        ),
        ("language_model_note", " "),
    ],
    ids=[
        "dropped",
        "renamed",
        "repeated",
        "a stray bracket",
        "a nested field",
        "a format",
        "a conversion",
        "an extra one",
        "two that change places",
        "empty",
    ],
)
def test_one_text_that_does_not_fit_leaves_every_text_in_english(monkeypatch, field, translation):
    stub_the_translation(monkeypatch, GERMAN | {field: translation})
    assert report.translate_texts("German") == ENGLISH


@pytest.mark.parametrize(
    "stop_reason, parses", [("max_tokens", True), ("end_turn", False)], ids=["cut off", "no parse"]
)
def test_a_translation_that_is_cut_off_or_does_not_parse_leaves_the_texts_in_english(
    monkeypatch, stop_reason, parses
):
    stub_the_translation(monkeypatch, GERMAN, stop_reason, parses)
    assert report.translate_texts("German") == ENGLISH


def test_a_failed_translation_call_leaves_the_texts_in_english(monkeypatch):
    def fail(request):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://example.org"))

    monkeypatch.setattr(report, "build_translation_model", lambda: RunnableLambda(fail))
    assert report.translate_texts("German") == ENGLISH
