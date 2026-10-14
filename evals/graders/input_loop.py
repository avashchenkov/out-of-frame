"""Code-based grader for the input loop, see docs/eval-architecture.md#input-loop: only the
input state at the end is graded. An agent that asks after the replies have run out, or
geocodes a text with no recorded response, ends with an input that is not complete, so this
grade fails it.

TODO: the destinations and their departure times, with I1 and I3 (step 9).
"""

from evals.graders.finding import Grade
from out_of_frame.state import Coordinates, RunState


def grade_property(state: RunState, expected: Coordinates) -> Grade:
    """The input ends with the property at the building that the user's replies lead to."""
    found = state.property.coordinates if state.property else None
    reasons = () if found == expected else (f"the property is {state.property!r}",)
    return Grade("property", not reasons, reasons)
