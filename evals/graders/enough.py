"""The code-based grader for the decision to stop, see docs/eval-architecture.md#llm-steps."""

from dataclasses import dataclass

from evals.graders.finding import Grade
from out_of_frame.state import ToolCall


@dataclass(frozen=True)
class ExpectedDecision:
    """What an Enough task's decision must be: one of the three is given."""

    stops: bool | None = None  # whether it stops, or makes one more tool call
    reads: str | None = None  # the URL of a page that it must read
    leaves_unread: str | None = None  # the URL of a page that it must not read


def grade_decision(call: ToolCall | None, expected: ExpectedDecision) -> Grade:
    """The model stops or goes on as expected; a page is read only by an extract call of its
    URL, never by any other call. A failure says what the model did."""
    read = call.url if call is not None and call.tool == "extract" else None
    if expected.stops is not None:
        passed = (call is None) == expected.stops
    elif expected.reads is not None:
        passed = read == expected.reads
    else:
        passed = read != expected.leaves_unread
    if passed:
        return Grade("decision", True)
    made = "it stops" if call is None else f"it calls {call.tool} with {call.argument!r}"
    return Grade("decision", False, (made,))
