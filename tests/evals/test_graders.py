"""Each code-based grader on a hand-written outcome it must pass and one it must fail."""

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
        evidence_ids=["web-1"],
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


def test_grounding_passes_with_cited_facts_from_a_page_and_the_map():
    grade = grade_grounding(
        finding(
            key_facts=["Test GmbH runs a bakery", "Teststraße 1"], evidence_ids=["web-1", "map-1"]
        ),
        MAP_OBJECT,
        [PAGE],
    )
    assert grade.passed


def test_grounding_fails_on_an_unknown_evidence_id():
    assert not grade_grounding(finding(evidence_ids=["web-9"]), MAP_OBJECT, [PAGE]).passed


def test_grounding_fails_on_a_key_fact_not_in_the_cited_source():
    grade = grade_grounding(finding(key_facts=["Test GmbH runs a brewery"]), MAP_OBJECT, [PAGE])
    assert not grade.passed


def test_grounding_fails_on_a_fact_from_a_source_the_finding_does_not_cite():
    grade = grade_grounding(finding(evidence_ids=["map-1"]), MAP_OBJECT, [PAGE])
    assert not grade.passed


def test_grounding_fails_on_an_identified_finding_without_evidence():
    assert not grade_grounding(finding(key_facts=[], evidence_ids=[]), MAP_OBJECT, [PAGE]).passed


def test_grounding_passes_on_an_unidentified_finding_without_evidence():
    unidentified = finding(
        outcome="unidentified", identified_type=None, status=None, key_facts=[], evidence_ids=[]
    )
    assert grade_grounding(unidentified, MAP_OBJECT, [PAGE]).passed


def test_grounding_fails_on_an_empty_key_fact():
    assert not grade_grounding(finding(key_facts=[" "]), MAP_OBJECT, [PAGE]).passed


def test_grounding_fails_when_two_sources_have_the_same_id():
    other = PAGE.model_copy(update={"content": "Test GmbH runs a chemical plant."})
    assert not grade_grounding(finding(), MAP_OBJECT, [PAGE, other]).passed


def test_grounding_fails_when_a_page_has_the_id_of_the_map_source():
    page = PAGE.model_copy(update={"id": "map-1"})
    cited = finding(evidence_ids=["map-1"], key_facts=["Teststraße 1"])
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
