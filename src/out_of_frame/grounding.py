"""The grounding check of a finding, see docs/architecture.md#grounding. The investigation and
the evals' grounding grader run the same check."""

import re
import unicodedata

from out_of_frame.state import Finding, MapObject, Source


def grounding_errors(finding: Finding, map_object: MapObject, sources: list[Source]) -> list[str]:
    """Why the finding is not grounded; empty if it is. Each evidence ID must exist, and each
    key fact must appear word for word in a cited source.

    An identified finding cites at least one source and one key fact; an unidentified one may
    cite nothing. For the object's own map or plan data, the cited text is its map_text().
    """
    errors = []
    if finding.outcome == "identified" and not (finding.evidence_ids and finding.key_facts):
        errors.append("an identified finding needs an evidence ID and a key fact")
    ids = [source.id for source in sources] + [map_object.source_id]
    if len(set(ids)) != len(ids):
        errors.append("two sources have the same ID")
    texts = {source.id: source.content for source in sources}
    texts[map_object.source_id] = map_object.map_text()
    errors += [f"unknown evidence ID {id!r}" for id in finding.evidence_ids if id not in texts]
    cited = [texts[id] for id in finding.evidence_ids if id in texts]
    for fact in finding.key_facts:
        if not fact.strip():
            errors.append("an empty key fact")
        elif not any(appears_in(fact, text) for text in cited):
            errors.append(f"key fact not found word for word in a cited source: {fact!r}")
    return errors


def normalise(text: str) -> str:
    """One Unicode form and single spaces: the same words written with other code points match.

    This covers a decomposed "ü" and a no-break space, which pages often use.
    """
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def appears_in(fact: str, text: str) -> bool:
    """The fact appears as whole words: "Klärwerkstraße 1" is not in "Klärwerkstraße 1a"."""
    fact = normalise(fact)
    before = r"(?<!\w)" if re.match(r"\w", fact[:1]) else ""
    after = r"(?!\w)" if re.match(r"\w", fact[-1:]) else ""
    return re.search(before + re.escape(fact) + after, normalise(text)) is not None
