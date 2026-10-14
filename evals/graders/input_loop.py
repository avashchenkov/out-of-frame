"""Code-based grader for the input loop, see docs/eval-architecture.md#input-loop: only the
input state at the end is graded. An agent that asks after the replies have run out, or
geocodes a text with no recorded response, ends with an input that is not complete, so this
grade fails it.
"""

import datetime as dt
from collections import Counter

from evals.graders.finding import Grade
from out_of_frame.record import Record
from out_of_frame.state import Coordinates, RunState


class ExpectedDestination(Record):
    """A place that the user travels to, as the input should end: its building and both of its
    clock times. Its name is free."""

    coordinates: Coordinates
    leave_home: dt.time
    leave_place: dt.time


class ExpectedInput(Record):
    property: Coordinates
    destinations: list[ExpectedDestination]  # empty if the user travels nowhere


def grade_property(state: RunState, expected: Coordinates) -> Grade:
    """The input ends with the property at the building that the user's replies lead to."""
    found = state.property.coordinates if state.property else None
    reasons = () if found == expected else (f"the property is {state.property!r}",)
    return Grade("property", not reasons, reasons)


def grade_destinations(state: RunState, expected: list[ExpectedDestination]) -> Grade:
    """The input ends with each expected place, at its building and with both of its clock
    times, and with no other place, in any order."""
    found = [
        ExpectedDestination(
            coordinates=destination.address.coordinates,
            leave_home=destination.leave_home,
            leave_place=destination.leave_place,
        )
        for destination in state.destinations or []
        if destination.address is not None
        and destination.address.coordinates is not None
        and destination.leave_home is not None
        and destination.leave_place is not None
    ]
    complete = state.destinations is not None and len(found) == len(state.destinations)
    passed = complete and Counter(found) == Counter(expected)
    reasons = () if passed else (f"the destinations are {state.destinations!r}",)
    return Grade("destinations", passed, reasons)
