"""Each code-based grader on a hand-written outcome it must pass and one it must fail."""

import datetime as dt

import pytest

from evals.graders.end_to_end import AddressLabel, grade_findings, grade_journeys
from evals.graders.finding import Expected, grade_grounding, grade_result
from evals.graders.input_loop import ExpectedDestination, grade_destinations
from evals.graders.prompt_injection import grade_flagged
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


def test_result_checks_the_cited_source_only_where_the_task_names_one():
    on_the_map = Expected("identified", "production", "operating", evidence_id="map-1")
    assert grade_result(finding(evidence_id="map-1"), MAP_OBJECT, on_the_map).passed
    assert not grade_result(finding(), MAP_OBJECT, on_the_map).passed
    assert grade_result(finding(evidence_id="map-1"), MAP_OBJECT, EXPECTED).passed


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


# The end-to-end graders: findings against the labels of an address, and the journeys.
SITE = MAP_OBJECT.model_copy(
    update={"id": "osm-way-1", "details": {"category": "industry", "landuse": "industrial"}}
)


def label(**changes) -> AddressLabel:
    fields = dict(
        id="test-bakery",
        object_id="osm-way-1",
        category="industry",
        coordinates={"lat": 52.5, "lon": 13.4},
        distance_tolerance_m=100,
        identified_type="production",
        status="operating",
        source_url="https://example.org",
        search="Teststraße 1 Berlin",
    )
    return AddressLabel.model_validate(fields | changes)


def left_out(**changes) -> AddressLabel:
    fields = label().model_dump(exclude={"identified_type", "status", "source_url", "search"})
    return AddressLabel.model_validate(fields | {"left_out": "no page a search finds"} | changes)


def run_state(objects: list[MapObject], findings: list[Finding]) -> RunState:
    return RunState(map_objects=objects, findings=findings)


def site_finding(**changes) -> Finding:
    return finding(**({"map_object_id": "osm-way-1"} | changes))


def test_findings_match_a_label_by_object_id():
    # The labelled object is beyond the tolerance, and another object with a finding lies right
    # at the label: the object ID still decides.
    far = SITE.model_copy(update={"coordinates": Coordinates(lat=52.502, lon=13.4)})
    at_label = SITE.model_copy(update={"id": "osm-way-2"})
    findings = [site_finding(), site_finding(map_object_id="osm-way-2")]
    graded = grade_findings(run_state([far, at_label], findings), [label()])
    assert graded.results == {"test-bakery": "correct"} and graded.false_alarms == ("osm-way-2",)
    assert graded.precision == 0.5 and graded.recall == 1


def test_findings_match_a_label_by_coordinates_when_the_map_changed_the_id():
    moved = SITE.model_copy(
        update={"id": "osm-way-2", "coordinates": Coordinates(lat=52.5005, lon=13.4)}
    )
    graded = grade_findings(
        run_state([moved], [site_finding(map_object_id="osm-way-2")]), [label()]
    )
    assert graded.results == {"test-bakery": "correct"}


@pytest.mark.parametrize(
    "update",
    [
        {"coordinates": Coordinates(lat=52.502, lon=13.4)},  # about 220 m away
        {"details": {"category": "airport", "aeroway": "aerodrome"}},
    ],
    ids=["beyond the tolerance", "another category"],
)
def test_a_finding_that_matches_no_label_is_a_false_alarm(update):
    other = SITE.model_copy(update={"id": "osm-way-2"} | update)
    graded = grade_findings(
        run_state([other], [site_finding(map_object_id="osm-way-2")]), [label()]
    )
    assert graded.false_alarms == ("osm-way-2",) and graded.results == {
        "test-bakery": "not fetched"
    }
    assert graded.precision == 0 and graded.recall is None


def test_a_matched_finding_with_a_wrong_type_or_status_is_an_error():
    graded = grade_findings(run_state([SITE], [site_finding(status="closed")]), [label()])
    assert graded.results == {"test-bakery": "error"} and graded.precision == graded.recall == 0
    assert graded.reasons == ("test-bakery: status 'closed', expected 'operating'",)


def test_an_unidentified_finding_is_right_only_where_the_label_has_no_type():
    unidentified = Finding.unidentified("osm-way-1")
    state = run_state([SITE], [unidentified])
    assert grade_findings(state, [label()]).results == {"test-bakery": "error"}
    unknown = label(identified_type=None, status=None)
    assert grade_findings(state, [unknown]).results == {"test-bakery": "correct"}


def test_a_fetched_object_without_a_finding_is_a_miss():
    graded = grade_findings(run_state([SITE], []), [label()])
    assert graded.results == {"test-bakery": "miss"} and graded.recall == 0
    assert graded.precision is None


def test_a_label_left_out_is_not_scored_and_its_finding_is_no_false_alarm():
    graded = grade_findings(run_state([SITE], [site_finding()]), [left_out()])
    assert graded.results == {"test-bakery": "left out"} and not graded.false_alarms
    assert graded.precision is None and graded.recall is None


def test_a_second_finding_for_the_same_object_is_a_false_alarm():
    graded = grade_findings(run_state([SITE], [site_finding(), site_finding()]), [label()])
    assert graded.results == {"test-bakery": "correct"} and graded.false_alarms == ("osm-way-1",)
    assert graded.precision == 0.5


def test_a_label_whose_link_is_in_the_object_data_needs_no_search():
    assert label(search=None).search is None


def test_an_unidentified_finding_with_a_type_and_status_is_an_error():
    unidentified = site_finding(outcome="unidentified")
    graded = grade_findings(run_state([SITE], [unidentified]), [label()])
    assert graded.results == {"test-bakery": "error"}
    assert graded.reasons == ("test-bakery: outcome 'unidentified', expected 'identified'",)


def test_two_moved_objects_take_the_labels_closest_to_them():
    # Both labels' objects changed ID. The depot's new object, nearer the property, is a little
    # nearer the bakery's label than its own; the bakery's new object is right at its label.
    labels = [
        label(object_id="osm-way-8", distance_tolerance_m=300),
        label(
            id="test-depot",
            object_id="osm-way-9",
            coordinates={"lat": 52.502, "lon": 13.4},
            distance_tolerance_m=300,
            identified_type="logistics",
        ),
    ]
    near_depot = SITE.model_copy(
        update={"id": "osm-way-2", "coordinates": Coordinates(lat=52.5009, lon=13.4)}
    )
    near_bakery = SITE.model_copy(
        update={
            "id": "osm-way-3",
            "coordinates": Coordinates(lat=52.4999, lon=13.4),
            "distance_from_property_m": 300,
        }
    )
    findings = [
        site_finding(map_object_id="osm-way-2", identified_type="logistics"),
        site_finding(map_object_id="osm-way-3"),
    ]
    graded = grade_findings(run_state([near_depot, near_bakery], findings), labels)
    assert graded.results == {"test-bakery": "correct", "test-depot": "correct"}


def test_an_object_with_a_finding_takes_its_label_before_a_nearer_one_without():
    # The map changed the labelled object's ID; an unlabelled object nearer the label, also
    # within the tolerance, has no finding.
    nearer = SITE.model_copy(
        update={"id": "osm-way-2", "coordinates": Coordinates(lat=52.5002, lon=13.4)}
    )
    moved = SITE.model_copy(
        update={
            "id": "osm-way-3",
            "coordinates": Coordinates(lat=52.5015, lon=13.4),
            "distance_from_property_m": 200,
        }
    )
    state = run_state([nearer, moved], [site_finding(map_object_id="osm-way-3")])
    graded = grade_findings(state, [label(distance_tolerance_m=300)])
    assert graded.results == {"test-bakery": "correct"} and not graded.false_alarms


def test_each_label_matches_one_object_at_most():
    near = SITE.model_copy(update={"id": "osm-way-2"})
    findings = [site_finding(), site_finding(map_object_id="osm-way-2")]
    graded = grade_findings(run_state([SITE, near], findings), [label()])
    assert graded.false_alarms == ("osm-way-2",)


@pytest.mark.parametrize(
    "changes, error",
    [
        ({"left_out": "no page"}, "has no identified_type"),
        ({"source_url": None}, "address of its page"),
        ({"distance_tolerance_m": 0}, "greater than 0"),
        ({"distance_tolerance_m": float("inf")}, "finite"),
    ],
    ids=["left out with a type", "scored without a page", "no tolerance", "endless tolerance"],
)
def test_a_label_is_scored_or_left_out(changes, error):
    with pytest.raises(ValueError, match=error):
        label(**changes)
    with pytest.raises(ValueError, match="or left_out"):
        AddressLabel.model_validate(left_out().model_dump(exclude_unset=True, exclude={"left_out"}))


HOME = Address(text="Teststraße 1, 10115 Berlin", coordinates=Coordinates(lat=52.5, lon=13.4))
WORK_PLACE = ExpectedDestination(
    coordinates=Coordinates(lat=52.52, lon=13.41),
    leave_home=dt.time(8),
    leave_place=dt.time(17),
    there="found",
    back="found",
)
WORK = Destination(
    id="destination-1",
    name="work",
    address=Address(text="Work 1", coordinates=WORK_PLACE.coordinates),
    leave_home=dt.time(8),
    leave_place=dt.time(17),
)


def journeys(*outcomes: str) -> RunState:
    trips = [
        Journey.model_validate(
            {"destination_id": "destination-1", "direction": direction, "outcome": outcome}
        )
        for direction, outcome in zip(["there", "back"], outcomes, strict=False)
    ]
    return RunState(property=HOME, destinations=[WORK], journeys=trips)


def test_journeys_pass_there_and_back_with_the_expected_outcome():
    assert grade_journeys(journeys("found", "found"), [WORK_PLACE]).passed


def test_a_journey_that_transitous_could_not_plan_is_not_graded_on_its_outcome():
    assert grade_journeys(journeys("found", "unavailable"), [WORK_PLACE]).passed


@pytest.mark.parametrize(
    "state, expected",
    [
        (journeys("found"), [WORK_PLACE]),
        (journeys("found", "no route"), [WORK_PLACE]),
        (journeys("found", "found"), []),
    ],
    ids=["no journey back", "another outcome", "a journey without a destination"],
)
def test_journeys_fail_when_one_is_missing_wrong_or_not_asked_for(state, expected):
    graded = grade_journeys(state, expected)
    assert not graded.passed and graded.reasons


@pytest.mark.parametrize("time", ["leave_home", "leave_place"])
def test_two_places_in_one_building_keep_their_own_journeys(time):
    gym = WORK.model_copy(update={"id": "destination-2", "name": "gym", time: dt.time(21)})
    gym_place = WORK_PLACE.model_copy(update={time: dt.time(21)})
    trips = [
        Journey(destination_id=place, direction=direction, outcome="found")
        for place in ("destination-1", "destination-2")
        for direction in ("there", "back")
    ]
    state = RunState(property=HOME, destinations=[WORK, gym], journeys=trips)
    assert grade_journeys(state, [WORK_PLACE, gym_place]).passed


def test_the_input_is_graded_without_the_journeys():
    assert grade_destinations(journeys("found", "found"), [WORK_PLACE]).passed
