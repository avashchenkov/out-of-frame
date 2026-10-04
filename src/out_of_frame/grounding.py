"""What "word for word" means when a key fact is checked against a source, see
docs/architecture.md#grounding. The agent's grounding check and the evals share these rules.

TODO: the grounding check itself, with the investigation in step 5.
"""

import re
import unicodedata

from out_of_frame.state import NearbyObject


def normalise(text: str) -> str:
    """One Unicode form and single spaces: the same words written with other code points match.

    This covers a decomposed "ü" and a no-break space, which pages often use.
    """
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def object_text(obj: NearbyObject) -> str:
    """The object's own map or plan data as text: its name, details and addresses."""
    lines = [obj.name or ""] + [f"{key}={value}" for key, value in obj.details.items()]
    return "\n".join(lines + obj.addresses)


def appears_in(fact: str, text: str) -> bool:
    """The fact appears as whole words: "Klärwerkstraße 1" is not in "Klärwerkstraße 1a"."""
    fact = normalise(fact)
    before = r"(?<!\w)" if re.match(r"\w", fact[:1]) else ""
    after = r"(?!\w)" if re.match(r"\w", fact[-1:]) else ""
    return re.search(before + re.escape(fact) + after, normalise(text)) is not None
