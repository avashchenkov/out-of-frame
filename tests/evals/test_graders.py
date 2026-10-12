"""Each code-based grader on a hand-written outcome it must pass and one it must fail."""

import pytest

from evals.graders.finding import Expected, grade_grounding, grade_result
from evals.graders.prompt_injection import grade_flagged
from out_of_frame.state import Coordinates, Finding, MapObject, Source

MAP_OBJECT = MapObject(
    id="obj-1",
    name=None,
    details={"landuse": "industrial"},
    addresses=["Teststraße 1, 10115 Berlin"],
    coordinates=Coordinates(lat=52.5, lon=13.4),
    distance_from_property_m=100,
    source_id="map-1",
)
EXPECTED = Expected("identified", "production", "operating")
PAGE = Source(
    id="web-1",
    kind="web search",
    request="Teststraße 1 Berlin",
    url="https://example.org",
    content="Test GmbH runs a bakery at Teststraße 1, 10115 Berlin.",
)


def finding(**changes) -> Finding:
    fields = dict(
        map_object_id="obj-1",
        outcome="identified",
        identified_type="production",
        status="operating",
        key_facts=["Test GmbH runs a bakery"],
        evidence_id="web-1",
    )
    return Finding.model_validate(fields | changes)


def test_result_passes_when_outcome_type_and_status_match():
    grade = grade_result(finding(), MAP_OBJECT, EXPECTED)
    assert grade.passed


def test_result_fails_on_a_wrong_type():
    grade = grade_result(finding(identified_type="plant"), MAP_OBJECT, EXPECTED)
    assert not grade.passed
    assert grade.reasons == ("identified_type: 'plant', expected 'production'",)


def test_result_fails_on_a_finding_about_another_map_object():
    grade = grade_result(finding(map_object_id="obj-2"), MAP_OBJECT, EXPECTED)
    assert not grade.passed


def test_grounding_passes_with_facts_from_the_cited_page_and_the_map():
    grade = grade_grounding(
        finding(key_facts=["Test GmbH runs a bakery", "landuse=industrial"]), MAP_OBJECT, [PAGE]
    )
    assert grade.passed


def test_grounding_passes_with_facts_from_the_map_alone():
    from_the_map = finding(key_facts=["Teststraße 1"], evidence_id="map-1")
    assert grade_grounding(from_the_map, MAP_OBJECT, [PAGE]).passed


def test_grounding_fails_on_an_unknown_evidence_id():
    assert not grade_grounding(finding(evidence_id="web-9"), MAP_OBJECT, [PAGE]).passed


def test_grounding_fails_on_a_key_fact_not_in_the_cited_source():
    grade = grade_grounding(finding(key_facts=["Test GmbH runs a brewery"]), MAP_OBJECT, [PAGE])
    assert not grade.passed


def test_grounding_fails_on_a_fact_from_a_page_the_finding_does_not_cite():
    other = PAGE.model_copy(
        update={"id": "web-2", "url": "https://example.com", "content": "Other GmbH, Teststraße 9."}
    )
    grade = grade_grounding(finding(evidence_id="web-2"), MAP_OBJECT, [PAGE, other])
    assert not grade.passed


def test_grounding_takes_a_snippet_and_the_full_text_of_one_page_as_one_page():
    full_text = PAGE.model_copy(update={"id": "web-2", "content": "A bakery since 1990."})
    two_parts = finding(key_facts=["Test GmbH runs a bakery", "A bakery since 1990"])
    grade = grade_grounding(
        two_parts.model_copy(update={"evidence_id": "web-2"}), MAP_OBJECT, [PAGE, full_text]
    )
    assert grade.passed


def test_grounding_fails_on_an_identified_finding_without_its_source():
    from_the_map = finding(key_facts=["Teststraße 1"], evidence_id=None)
    assert not grade_grounding(from_the_map, MAP_OBJECT, [PAGE]).passed


def test_grounding_fails_on_an_identified_finding_without_key_facts():
    assert not grade_grounding(finding(key_facts=[]), MAP_OBJECT, [PAGE]).passed


def test_grounding_fails_on_a_page_fact_when_the_finding_cites_the_map():
    from_the_map = finding(key_facts=["Test GmbH runs a bakery"], evidence_id="map-1")
    assert not grade_grounding(from_the_map, MAP_OBJECT, [PAGE]).passed


@pytest.mark.parametrize(
    "cited, reasons", [("web-1", ("an unidentified finding cites no page",)), ("map-1", ())]
)
def test_an_unidentified_finding_may_cite_its_map_data_but_no_page(cited, reasons):
    unidentified = finding(
        outcome="unidentified", identified_type=None, status=None, key_facts=[], evidence_id=cited
    )
    assert grade_grounding(unidentified, MAP_OBJECT, [PAGE]).reasons == reasons


def test_grounding_fails_on_a_cited_page_that_gives_no_key_fact():
    from_the_map = finding(key_facts=["landuse=industrial"])  # cites web-1, quotes the map
    grade = grade_grounding(from_the_map, MAP_OBJECT, [PAGE])
    assert grade.reasons == ("no key fact comes from the cited page 'web-1'",)


def test_grounding_tells_an_unknown_evidence_id_once():
    grade = grade_grounding(finding(evidence_id="web-9"), MAP_OBJECT, [PAGE])
    assert grade.reasons == (
        "unknown evidence ID 'web-9'",
        "key fact not found word for word in the cited page or the map data: "
        "'Test GmbH runs a bakery'",
    )


def test_grounding_passes_on_an_unidentified_finding_without_evidence():
    unidentified = finding(
        outcome="unidentified", identified_type=None, status=None, key_facts=[], evidence_id=None
    )
    assert grade_grounding(unidentified, MAP_OBJECT, [PAGE]).passed


def test_grounding_fails_on_an_empty_key_fact():
    assert not grade_grounding(finding(key_facts=[" "]), MAP_OBJECT, [PAGE]).passed


def test_grounding_fails_when_two_sources_have_the_same_id():
    other = PAGE.model_copy(update={"content": "Test GmbH runs a chemical plant."})
    assert not grade_grounding(finding(), MAP_OBJECT, [PAGE, other]).passed


def test_grounding_fails_when_a_page_has_the_id_of_the_map_source():
    page = PAGE.model_copy(update={"id": "map-1"})
    cited = finding(evidence_id="map-1", key_facts=["Teststraße 1"])
    grade = grade_grounding(cited, MAP_OBJECT, [page])
    assert not grade.passed


def test_grounding_matches_the_same_words_in_other_code_points():
    # A decomposed "ü" and a no-break space on the page; the usual forms in the fact.
    page = PAGE.model_copy(update={"content": "Mu\u0308ller\u00a0KFZ-Service runs a garage."})
    assert grade_grounding(finding(key_facts=["Müller KFZ-Service"]), MAP_OBJECT, [page]).passed


def test_flagged_passes_when_the_check_flags_a_planted_page():
    assert grade_flagged(True, expected=True).passed


def test_flagged_fails_on_a_miss_and_on_a_false_alarm():
    miss, false_alarm = grade_flagged(False, expected=True), grade_flagged(True, expected=False)
    assert not miss.passed and miss.reasons[0].startswith("miss")
    assert not false_alarm.passed and false_alarm.reasons[0].startswith("false alarm")
