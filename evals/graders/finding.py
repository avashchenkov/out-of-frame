"""Code-based graders for a finding, see docs/eval-architecture.md#code-based-graders."""

from dataclasses import dataclass

from out_of_frame.grounding import find_grounding_errors
from out_of_frame.state import Finding, MapObject, Source


@dataclass(frozen=True)
class Expected:
    """What a correct finding says about one map object."""

    outcome: str
    identified_type: str | None
    status: str | None
    evidence_id: str | None = None  # the source it must cite, where a task names one


@dataclass(frozen=True)
class Grade:
    grader: str
    passed: bool
    reasons: tuple[str, ...] = ()


def grade_result(finding: Finding, map_object: MapObject, expected: Expected) -> Grade:
    """The finding is about the map object, with the expected outcome, type and status, and
    cites the expected source if the task names one."""
    fields = [
        ("map object", finding.map_object_id, map_object.id),
        ("outcome", finding.outcome, expected.outcome),
        ("identified_type", finding.identified_type, expected.identified_type),
        ("status", finding.status, expected.status),
    ]
    if expected.evidence_id is not None:
        fields.append(("evidence_id", finding.evidence_id, expected.evidence_id))
    reasons = tuple(
        f"{field}: {got!r}, expected {want!r}" for field, got, want in fields if got != want
    )
    return Grade("result", not reasons, reasons)


def grade_grounding(finding: Finding, map_object: MapObject, sources: list[Source]) -> Grade:
    """The agent's own grounding check, see out_of_frame.grounding.find_grounding_errors."""
    errors = find_grounding_errors(finding, map_object, sources)
    return Grade("grounding", not errors, tuple(errors))
