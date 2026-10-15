"""The commute: journeys by public transport between the property and each destination, from
Transitous, see docs/architecture.md#one-run and docs/sources.md#transitous."""

import datetime as dt
import logging
import statistics
import time
from typing import Literal, NamedTuple
from zoneinfo import ZoneInfo

import httpx

from out_of_frame.config import SOURCE_ATTEMPTS, TRANSITOUS_URL, USER_AGENT
from out_of_frame.state import Coordinates, Destination, Journey

log = logging.getLogger(__name__)

BERLIN_TIME = ZoneInfo("Europe/Berlin")  # the user's times are Berlin's
# The days, as month and day, without a normal timetable: Berlin's public holidays on a fixed
# date, and 24 and 31 December. Berlin's movable holidays never fall on a Wednesday.
NO_NORMAL_TIMETABLE = {(1, 1), (3, 8), (5, 1), (10, 3), (12, 24), (12, 25), (12, 26), (12, 31)}
CONNECTIONS = 3  # a journey's duration is the mean of the first three connections


class Connection(NamedTuple):
    """One connection that Transitous finds: when it leaves, and how long it takes."""

    leaves: dt.datetime
    duration_s: int


class TransitError(Exception):
    """Transitous failed after its retries. That journey is then unavailable, and the others are
    still planned, see docs/architecture.md#failures."""


def plan_journeys(
    home: Coordinates, destinations: list[Destination], date: dt.date
) -> list[Journey]:
    """Two journeys per destination on a normal weekday after the date: there, when the user
    leaves home, and back, when they leave the destination."""
    day = choose_day(date)
    journeys = []
    for destination in destinations:
        # The input is complete only with these, see conversation.find_missing.
        assert destination.address is not None and destination.address.coordinates is not None
        assert destination.leave_home is not None and destination.leave_place is not None
        place, id = destination.address.coordinates, destination.id
        journeys += [
            plan_journey(id, "there", home, place, at(day, destination.leave_home)),
            plan_journey(id, "back", place, home, at(day, destination.leave_place)),
        ]
    return journeys


def choose_day(date: dt.date) -> dt.date:
    """The first Wednesday after the date with a normal timetable."""
    day = date + dt.timedelta(days=1)
    while day.weekday() != 2 or (day.month, day.day) in NO_NORMAL_TIMETABLE:
        day += dt.timedelta(days=1)
    return day


def at(day: dt.date, clock: dt.time) -> dt.datetime:
    """The moment of the day at the clock time in Berlin, in summer or winter time."""
    return dt.datetime.combine(day, clock, tzinfo=BERLIN_TIME)


def plan_journey(
    destination_id: str,
    direction: Literal["there", "back"],
    start: Coordinates,
    end: Coordinates,
    leave: dt.datetime,
) -> Journey:
    """One journey: found with its mean duration, no route if no connection leaves at the time
    or later, or unavailable if Transitous failed."""
    journey = Journey(destination_id=destination_id, direction=direction, outcome="no route")
    try:
        connections = call_transitous(start, end, leave)
    except TransitError as error:
        log.warning("the journey %s to %s failed: %s", direction, destination_id, error)
        return journey.model_copy(update={"outcome": "unavailable"})
    durations = find_durations(connections, leave)
    if not durations:
        return journey
    mean = dt.timedelta(seconds=statistics.mean(durations))
    return journey.model_copy(update={"outcome": "found", "mean_duration": mean})


def find_durations(connections: list[Connection], leave: dt.datetime) -> list[int]:
    """The durations, in seconds, of the first connections that leave at the time or later.
    Transitous can give several connections that leave at one time, with other transfers: of
    those, the fastest counts."""
    fastest: dict[dt.datetime, int] = {}
    for leaves, duration_s in connections:
        if leaves >= leave and (leaves not in fastest or duration_s < fastest[leaves]):
            fastest[leaves] = duration_s
    return [fastest[leaves] for leaves in sorted(fastest)[:CONNECTIONS]]


def call_transitous(start: Coordinates, end: Coordinates, leave: dt.datetime) -> list[Connection]:
    """The connections that Transitous finds from start to end around the time, tried again on
    any failure, an answer that code cannot read too. No walk is asked for as a direct route:
    Transitous would then drop the connections slower than the walk."""
    params = {
        "fromPlace": f"{start.lat},{start.lon}",
        "toPlace": f"{end.lat},{end.lon}",
        "time": leave.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # A minimum, and one departure can have several: five leave room for three departures.
        "numItineraries": 5,
        "directModes": "",
        "detailedLegs": "false",  # half the response, and code reads no leg
    }
    for attempt in range(1, SOURCE_ATTEMPTS + 1):
        try:
            response = httpx.get(
                TRANSITOUS_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=60
            )
            response.raise_for_status()
            return [
                Connection(
                    dt.datetime.fromisoformat(itinerary["startTime"]), int(itinerary["duration"])
                )
                for itinerary in response.json()["itineraries"]
            ]
        # ValueError: a cut-off JSON or a bad value; KeyError, TypeError: a field is missing.
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            if attempt == SOURCE_ATTEMPTS:
                raise TransitError(f"{SOURCE_ATTEMPTS} tries failed: {error!r}") from error
            time.sleep(attempt)
    raise ValueError("OUT_OF_FRAME_SOURCE_ATTEMPTS must be at least 1")
