"""Each code-based grader on a hand-written outcome it must pass and one it must fail."""

from evals.graders.finding import Expected, grade_grounding, grade_result
from out_of_frame.state import Finding, NearbyObject, Point, Source

OBJECT = NearbyObject(
    id="obj-1",
    class_="industry",
    name=None,
    details={"landuse": "industrial"},
    addresses=["Teststraße 1, 10115 Berlin"],
    point=Point(lat=52.5, lon=13.4),
    distance_m=100,
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
        object_id="obj-1",
        outcome="identified",
        type="production",
        status="operating",
        why_it_matters="A bakery can bring early deliveries.",
        key_facts=["Test GmbH runs a bakery"],
        evidence_ids=["web-1"],
    )
    return Finding(**fields | changes)


def test_result_passes_when_outcome_type_and_status_match():
    grade = grade_result(finding(), OBJECT, EXPECTED)
    assert grade.passed


def test_result_fails_on_a_wrong_type():
    grade = grade_result(finding(type="plant"), OBJECT, EXPECTED)
    assert not grade.passed
    assert grade.reasons == ("type: 'plant', expected 'production'",)


def test_result_fails_on_a_finding_about_another_object():
    grade = grade_result(finding(object_id="obj-2"), OBJECT, EXPECTED)
    assert not grade.passed


def test_grounding_passes_with_cited_facts_from_a_page_and_the_map():
    grade = grade_grounding(
        finding(
            key_facts=["Test GmbH runs a bakery", "Teststraße 1"], evidence_ids=["web-1", "map-1"]
        ),
        OBJECT,
        [PAGE],
    )
    assert grade.passed


def test_grounding_fails_on_an_unknown_evidence_id():
    assert not grade_grounding(finding(evidence_ids=["web-9"]), OBJECT, [PAGE]).passed


def test_grounding_fails_on_a_key_fact_not_in_the_cited_source():
    grade = grade_grounding(finding(key_facts=["Test GmbH runs a brewery"]), OBJECT, [PAGE])
    assert not grade.passed


def test_grounding_fails_on_a_fact_from_a_source_the_finding_does_not_cite():
    grade = grade_grounding(finding(evidence_ids=["map-1"]), OBJECT, [PAGE])
    assert not grade.passed


def test_grounding_fails_on_an_identified_finding_without_evidence():
    assert not grade_grounding(finding(key_facts=[], evidence_ids=[]), OBJECT, [PAGE]).passed


def test_grounding_passes_on_an_unidentified_finding_without_evidence():
    unidentified = finding(
        outcome="unidentified", type="unknown", status="unknown", key_facts=[], evidence_ids=[]
    )
    assert grade_grounding(unidentified, OBJECT, [PAGE]).passed


def test_grounding_fails_on_an_empty_key_fact():
    assert not grade_grounding(finding(key_facts=[" "]), OBJECT, [PAGE]).passed


def test_grounding_fails_when_two_sources_have_the_same_id():
    other = PAGE.model_copy(update={"content": "Test GmbH runs a chemical plant."})
    assert not grade_grounding(finding(), OBJECT, [PAGE, other]).passed


def test_grounding_fails_when_a_page_has_the_id_of_the_map_source():
    page = PAGE.model_copy(update={"id": "map-1"})
    cited = finding(evidence_ids=["map-1"], key_facts=["Teststraße 1"])
    grade = grade_grounding(cited, OBJECT, [page])
    assert not grade.passed


def test_grounding_matches_the_same_words_in_other_code_points():
    # A decomposed "ü" and a no-break space on the page; the usual forms in the fact.
    page = PAGE.model_copy(update={"content": "Mu\u0308ller\u00a0KFZ-Service runs a garage."})
    assert grade_grounding(finding(key_facts=["Müller KFZ-Service"]), OBJECT, [page]).passed
