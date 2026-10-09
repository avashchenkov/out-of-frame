"""The grounding check of a finding, see docs/architecture.md#grounding. The investigation and
the evals' grounding grader run the same check."""

import re
import unicodedata

from out_of_frame.state import Finding, MapObject, Source


def find_grounding_errors(
    finding: Finding, map_object: MapObject, sources: list[Source]
) -> list[str]:
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


# A number with its decimal or thousands separators, a word, or any other character.
TOKEN = re.compile(r"\w*\d(?:[.,]\d+)+\w*|\w+|[^\w\s]")
MARKUP = "|`"  # table and code markup, which pages use for layout


def split_into_words(text: str) -> list[str]:
    """The text's words, numbers and symbols, in one Unicode form and in lower case.

    Spaces, punctuation and markup between them are left out: a page's typography is not a
    fact. A symbol such as ✓ or < can change a fact, so it stays, and so do a number's
    separators: 660.000 is not 660 000. Case is lowered word by word, and not casefolded, so
    that Maße stays apart from Masse.
    """
    tokens = TOKEN.findall(unicodedata.normalize("NFC", text))
    return [token.lower() for token in tokens if is_word_or_symbol(token)]


def is_word_or_symbol(token: str) -> bool:
    """A word or a number, or a symbol that is not markup; punctuation is neither."""
    if re.match(r"\w", token):
        return True
    return unicodedata.category(token).startswith("S") and token not in MARKUP


def appears_in(fact: str, text: str) -> bool:
    """The fact's words appear in the text in the same order, as whole words: "Gmbh -
    Klärwerkstraße 3" has "GmbH, Klärwerkstraße 3", but "Klärwerkstraße 1a" has not
    "Klärwerkstraße 1"."""
    fact_words = split_into_words(fact)
    return (
        bool(fact_words) and f" {' '.join(fact_words)} " in f" {' '.join(split_into_words(text))} "
    )
