"""Code-based graders for an end-to-end trial, see docs/eval-architecture.md#code-based-graders:
the findings against the labels, and the journeys. The input is graded as in the input loop.
"""

import math
from dataclasses import dataclass
from typing import Literal, Self

from pydantic import Field, model_validator

from evals.graders.finding import Grade
from evals.graders.input_loop import ExpectedDestination
from out_of_frame.map_objects import project
from out_of_frame.record import Record
from out_of_frame.state import Coordinates, Finding, RunState, Service


class AddressLabel(Record):
    """One object that the agent can see at an end-to-end address: its true type and status,
    or why it is not scored. See docs/eval-architecture.md#ground-truth-labels."""

    id: str  # for a human reviewer only
    object_id: str  # as the agent's code makes it
    category: str
    coordinates: Coordinates
    distance_tolerance_m: float = Field(gt=0, allow_inf_nan=False)
    identified_type: str | None = None  # None: the object cannot be identified
    status: str | None = None  # None: no source settles it
    source_url: str | None = None  # the address of one page that shows why the label is true
    # A Tavily search, from what the agent sees, that finds the page; None if the page's link is
    # in the object's own data, such as a plan's PDF, which the agent can read directly.
    search: str | None = None
    left_out: str | None = None  # why the object is not scored, such as no page it can reach

    @model_validator(mode="after")
    def check_scored_or_left_out(self) -> Self:
        given = {"identified_type", "status", "source_url", "search"} & self.model_fields_set
        if self.left_out is not None and given:
            raise ValueError(f"{self.id}: a label left out has no {', '.join(sorted(given))}")
        if self.left_out is None and len(given) < 4:
            raise ValueError(
                f"{self.id}: give identified_type, status, source_url and search, or left_out"
            )
        if self.left_out is None and not (self.source_url or "").startswith(
            ("https://", "http://")
        ):
            raise ValueError(f"{self.id}: a scored label needs the address of its page")
        if "TODO" in (self.id, self.search, self.left_out):
            raise ValueError(f"{self.id}: fill in every TODO of the labelling script")
        return self


class ExpectedRun(Record):
    """How an end-to-end run should end: the input, as in the input loop, with the outcome of
    each journey, and the labels of the objects the agent can see."""

    property: Coordinates
    destinations: list[ExpectedDestination]  # each with the outcome of its journeys
    labels: list[AddressLabel]
    recorded_as: str  # the fixtures' name, which evals/label.py recorded the labels' data under


type LabelResult = Literal["correct", "error", "miss", "not fetched", "left out"]


@dataclass(frozen=True)
class FindingsGrade:
    """The findings against the labels: each label's result, and the findings that match no
    label. See docs/eval-architecture.md#code-based-graders."""

    results: dict[str, LabelResult]  # by the label's id
    false_alarms: tuple[str, ...]  # the map object IDs of findings that match no label
    reasons: tuple[str, ...]  # why each error, for a person who looks into a failure


def match_labels(state: RunState, labels: list[AddressLabel]) -> dict[str, str]:
    """The label each map object matches, by the object's ID, each object and each label at
    most once: first by object ID, then, since a map edit can change an ID, by coordinates, to a
    label of the same category within its tolerance. Of the pairs by coordinates, those of an
    object with a finding go first, so that an object without one cannot take the label of the
    object a finding is about; then the closest pair first."""
    by_object_id = {label.object_id: label.id for label in labels}
    matched = {o.id: by_object_id[o.id] for o in state.map_objects if o.id in by_object_id}
    found = {finding.map_object_id for finding in state.findings}
    pairs = []
    for map_object in state.map_objects:
        for label in labels:
            distance = measure_distance_m(map_object.coordinates, label.coordinates)
            if (
                label.category == map_object.details["category"]
                and distance <= label.distance_tolerance_m
            ):
                pairs.append((map_object.id not in found, distance, map_object.id, label.id))
    for _, _, object_id, label_id in sorted(pairs):
        if object_id not in matched and label_id not in matched.values():
            matched[object_id] = label_id
    return matched


def measure_distance_m(a: Coordinates, b: Coordinates) -> float:
    return math.hypot(*project(a, (b.lat, b.lon)))


def grade_findings(state: RunState, labels: list[AddressLabel]) -> FindingsGrade:
    """Each label's result: correct if its finding has the right type and status, error if
    not, miss if its object was fetched but has no finding; not fetched if the trial did not
    fetch its object, as when its source failed; and left out if it is not scored. A finding
    that matches no label is a false alarm, and so is a second finding for the same object."""
    matched = match_labels(state, labels)
    by_id = {label.id: label for label in labels}
    results: dict[str, LabelResult] = {
        label.id: "not fetched" if label.id not in matched.values() else "miss" for label in labels
    }
    false_alarms, reasons, graded = [], [], set()
    for finding in state.findings:
        label_id = matched.get(finding.map_object_id)
        if label_id is None or label_id in graded:
            false_alarms.append(finding.map_object_id)
            continue
        graded.add(label_id)
        label = by_id[label_id]
        if label.left_out is not None:
            continue
        wrong = compare(finding, label)
        results[label_id] = "error" if wrong else "correct"
        reasons += [f"{label_id}: {reason}" for reason in wrong]
    for label in labels:
        if label.left_out is not None:
            results[label.id] = "left out"
    return FindingsGrade(results, tuple(false_alarms), tuple(reasons))


def compare(finding: Finding, label: AddressLabel) -> list[str]:
    """What the finding gets wrong: its outcome, type or status. A finding is unidentified
    exactly where the label has no type."""
    outcome = "unidentified" if label.identified_type is None else "identified"
    return [
        f"{field} {got!r}, expected {want!r}"
        for field, got, want in [
            ("outcome", finding.outcome, outcome),
            ("identified_type", finding.identified_type, label.identified_type),
            ("status", finding.status, label.status),
        ]
        if got != want
    ]


def grade_journeys(state: RunState, expected: list[ExpectedDestination]) -> Grade:
    """One journey there and one back for each destination, each with its expected outcome,
    and none without a destination. A journey that Transitous could not plan is not graded on
    its outcome: its source failed. A destination is found by its building and its clock
    times, so that two places in one building stay apart."""
    ids = {
        (destination.address.coordinates, destination.leave_home, destination.leave_place): (
            destination.id
        )
        for destination in state.destinations or []
        if destination.address is not None and destination.address.coordinates is not None
    }
    wanted = {
        (ids.get(place.key()), direction): outcome
        for place in expected
        for direction, outcome in [("there", place.there), ("back", place.back)]
    }
    reasons = []
    found = [(journey.destination_id, journey.direction) for journey in state.journeys]
    if sorted(found, key=str) != sorted(wanted, key=str):
        reasons.append(f"the journeys are {found}, expected {list(wanted)}")
    for journey in state.journeys:
        want = wanted.get((journey.destination_id, journey.direction))
        if want is not None and journey.outcome not in (want, "unavailable"):
            reasons.append(
                f"{journey.destination_id} {journey.direction}: {journey.outcome}, expected {want}"
            )
    return Grade("journeys", not reasons, tuple(reasons))


type BranchResult = Literal["ok", "empty", "failed"]


def mark_branches(state: RunState) -> dict[Service, BranchResult]:
    """Each research branch, and the web search of the investigations: failed if its service
    failed, empty if it gave nothing, and ok otherwise. Transit fails when it could not plan a
    journey, and web search when an investigation could not search, even if the others could;
    web search gives nothing if no finding cites a page."""
    gave: dict[Service, bool] = {
        "map": any(state.find_source_kind(o) == "map" for o in state.map_objects),
        "plans": any(state.find_source_kind(o) == "plans" for o in state.map_objects),
        "transit": bool(state.journeys),
        "web search": any(source.kind == "web search" for source in state.sources),
    }
    return {
        service: "failed" if service in state.failures else "ok" if given else "empty"
        for service, given in gave.items()
    }
