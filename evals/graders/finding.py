"""Code-based graders for a finding, see docs/eval-architecture.md#code-based-graders."""

from dataclasses import dataclass

from out_of_frame.grounding import appears_in
from out_of_frame.state import Finding, MapObject, Source


@dataclass(frozen=True)
class Expected:
    """What a correct finding says about one map object."""

    outcome: str
    identified_type: str | None
    status: str | None


@dataclass(frozen=True)
class Grade:
    grader: str
    passed: bool
    reasons: tuple[str, ...] = ()


def grade_result(finding: Finding, map_object: MapObject, expected: Expected) -> Grade:
    """The finding is about the map object, with the expected outcome, type and status."""
    reasons = tuple(
        f"{field}: {got!r}, expected {want!r}"
        for field, got, want in [
            ("map object", finding.map_object_id, map_object.id),
            ("outcome", finding.outcome, expected.outcome),
            ("identified_type", finding.identified_type, expected.identified_type),
            ("status", finding.status, expected.status),
        ]
        if got != want
    )
    return Grade("result", not reasons, reasons)


def grade_grounding(finding: Finding, map_object: MapObject, sources: list[Source]) -> Grade:
    """Each evidence ID exists, and each key fact appears word for word in a cited source.

    An identified finding cites at least one source and one key fact; an unidentified one may
    cite nothing. For the object's own map or plan data, the cited text is its map_text().
    """
    reasons = []
    if finding.outcome == "identified" and not (finding.evidence_ids and finding.key_facts):
        reasons.append("an identified finding needs an evidence ID and a key fact")
    ids = [source.id for source in sources] + [map_object.source_id]
    if len(set(ids)) != len(ids):
        reasons.append("two sources have the same ID")
    texts = {source.id: source.content for source in sources}
    texts[map_object.source_id] = map_object.map_text()
    reasons += [f"unknown evidence ID {id!r}" for id in finding.evidence_ids if id not in texts]
    cited = [texts[id] for id in finding.evidence_ids if id in texts]
    for fact in finding.key_facts:
        if not fact.strip():
            reasons.append("an empty key fact")
        elif not any(appears_in(fact, text) for text in cited):
            reasons.append(f"key fact not found word for word in a cited source: {fact!r}")
    return Grade("grounding", not reasons, tuple(reasons))
