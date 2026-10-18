"""Code-based graders for a report draft, see docs/eval-architecture.md#report. What a person
must read, such as an invented concern or "nothing found" for a failed source, is not graded
here: until the judges are calibrated in step 10, the drafts are read by hand."""

import re

from evals.graders.finding import Grade
from out_of_frame.report import CITATION, find_wrong_citations
from out_of_frame.state import RunState


def grade_citations(draft: str, state: RunState) -> Grade:
    """Every object is cited, and every citation is one known ID."""
    known = {map_object.id for map_object in state.map_objects}
    wrong = find_wrong_citations(draft, known)
    missing = sorted(known - set(CITATION.findall(draft)))
    reasons = [f"wrong citation: {citation}" for citation in wrong]
    reasons += [f"left out: {id}" for id in missing]
    return Grade("citations", not reasons, tuple(reasons))


def grade_distances(draft: str, state: RunState) -> Grade:
    """Each object's distance is in the draft as given, such as 118 m, or at 0 m, that the
    property lies in the object's area or right next to it."""
    reasons = []
    for map_object in state.map_objects:
        distance = map_object.rounded_distance_m()
        given = rf"(?<![\d.,]){distance}\s?m\b"
        if distance == 0:
            given += r"|\bproperty lies\b|\bnext to the property\b"
        if not re.search(given, draft, re.IGNORECASE):
            reasons.append(f"no distance {distance} m for {map_object.id}")
    return Grade("distances", not reasons, tuple(reasons))
