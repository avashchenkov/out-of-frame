"""The grounding check of a finding, see docs/architecture.md#grounding. The investigation and
the evals' grounding grader run the same check."""

import re
import unicodedata

from out_of_frame.state import Finding, MapObject, Source


def find_grounding_errors(
    finding: Finding, map_object: MapObject, sources: list[Source]
) -> list[str]:
    """Why the finding is not grounded; empty if it is. Its evidence ID must exist, and each
    key fact must appear word for word in the cited page or in the object's own map data.

    An identified finding cites one source and at least one key fact, and a cited page gives
    one of them at least, so that the report never cites a page no fact came from. An
    unidentified finding cites no page. For the object's own map or plan data, the text is its
    map_text().
    """
    errors = []
    cited = finding.evidence_id
    if finding.outcome == "identified" and (cited is None or not finding.key_facts):
        errors.append("an identified finding needs an evidence ID and a key fact")
    if finding.outcome == "unidentified" and collect_cited_page(cited, sources):
        errors.append("an unidentified finding cites no page")
    ids = [source.id for source in sources] + [map_object.source_id]
    if len(set(ids)) != len(ids):
        errors.append("two sources have the same ID")
    if cited is not None and cited not in ids:
        errors.append(f"unknown evidence ID {cited!r}")
    page = [source.content for source in collect_cited_page(cited, sources)]
    facts = [fact for fact in finding.key_facts if fact.strip()]
    from_page = [fact for fact in facts if any(appears_in(fact, text) for text in page)]
    if len(facts) < len(finding.key_facts):
        errors.append("an empty key fact")
    errors += [
        f"key fact not found word for word in the cited page or the map data: {fact!r}"
        for fact in facts
        if fact not in from_page and not appears_in(fact, map_object.map_text())
    ]
    if finding.outcome == "identified" and page and not from_page:
        errors.append(f"no key fact comes from the cited page {cited!r}")
    return errors


def collect_cited_page(evidence_id: str | None, sources: list[Source]) -> list[Source]:
    """Every web source with the cited source's URL: a search snippet and the full text of the
    same page get IDs of their own, but they are one page. Empty if the finding cites the map,
    or nothing."""
    urls = {s.url for s in sources if s.id == evidence_id and s.kind == "web search"}
    return [s for s in sources if s.url in urls and s.kind == "web search"]


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
