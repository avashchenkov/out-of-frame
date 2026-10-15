"""The journeys on recorded Transitous responses."""

import datetime as dt

import httpx
import pytest

from evals.load import FIXTURES
from out_of_frame import transit
from out_of_frame.config import SOURCE_ATTEMPTS, USER_AGENT
from out_of_frame.state import Address, Coordinates, Destination, Journey

FREIHEIT_22 = Coordinates(lat=52.5292863, lon=13.2357896)
KARL_MARX_ALLEE_3 = Coordinates(lat=52.5222886, lon=13.4189853)
WORK = Destination(
    id="destination-1",
    name="work",
    address=Address(text="Karl-Marx-Allee 3, 10178 Berlin", coordinates=KARL_MARX_ALLEE_3),
    leave_home=dt.time(7, 40),
    leave_place=dt.time(18, 10),
)
DATE = dt.date(2026, 10, 15)  # a Thursday: the journeys are on Wednesday, 21 October


def read_fixture(name: str) -> bytes:
    return (FIXTURES / "transitous" / name).read_bytes()


# Recorded for 07:40 on 21 October 2026, Berlin's summer time: the connections leave at 07:47
# (55 or 45 minutes), 07:48 (54), 07:50 (56, 54 or 52) and 07:57 (58 or 55). The fastest of
# the first three departures take 45, 54 and 52 minutes.
FOUND = read_fixture("freiheit-22-to-karl-marx-allee-3.json")
NO_ROUTE = read_fixture("freiheit-22-to-the-north-sea.json")


def fake_transitous(monkeypatch, *answers) -> list[dict]:
    """Transitous answers each request with the next answer: content to send, or an exception
    to raise. Returns the keyword arguments of each request."""
    requests, queue = [], list(answers)

    def get(url, **kwargs):
        requests.append(kwargs)
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(200, content=answer, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(transit.time, "sleep", lambda seconds: None)
    return requests


def test_each_destination_gets_a_journey_there_and_one_back(monkeypatch):
    requests = fake_transitous(monkeypatch, FOUND, NO_ROUTE)
    there, back = transit.plan_journeys(FREIHEIT_22, [WORK], DATE)
    assert there == Journey(
        destination_id="destination-1",
        direction="there",
        outcome="found",
        mean_duration=dt.timedelta(minutes=(45 + 54 + 52) / 3),
    )
    assert back == Journey(destination_id="destination-1", direction="back", outcome="no route")
    # There from home when the user leaves it, back from the place when they leave it, in UTC.
    assert [
        (request["params"]["fromPlace"], request["params"]["toPlace"], request["params"]["time"])
        for request in requests
    ] == [
        ("52.5292863,13.2357896", "52.5222886,13.4189853", "2026-10-21T05:40:00Z"),
        ("52.5222886,13.4189853", "52.5292863,13.2357896", "2026-10-21T16:10:00Z"),
    ]
    # No walk as a direct route, which would hide the slower connections.
    assert requests[0]["params"]["directModes"] == ""
    assert requests[0]["headers"] == {"User-Agent": USER_AGENT}


def test_a_failed_journey_is_unavailable_and_the_other_is_still_planned(monkeypatch):
    failures = [httpx.ConnectTimeout("no answer")] * SOURCE_ATTEMPTS
    requests = fake_transitous(monkeypatch, *failures, FOUND)
    early = WORK.model_copy(update={"leave_place": dt.time(7, 40)})  # as the recorded answer
    there, back = transit.plan_journeys(FREIHEIT_22, [early], DATE)
    assert there.outcome == "unavailable" and there.mean_duration is None
    assert back.outcome == "found"
    assert len(requests) == SOURCE_ATTEMPTS + 1


@pytest.mark.parametrize(
    "answer",
    [
        b'{"itineraries": [',
        b'{"error": "busy"}',
        b'{"itineraries": null}',
        b'{"itineraries": [{"duration": 1800}]}',
        b'{"itineraries": [{"startTime": "2026-10-21T05:47:00Z", "duration": null}]}',
    ],
    ids=["cut off", "an error", "null", "no start", "no duration"],
)
def test_an_answer_cut_off_or_without_its_connections_is_tried_again_and_then_fails(
    monkeypatch, answer
):
    requests = fake_transitous(monkeypatch, *[answer] * SOURCE_ATTEMPTS)
    with pytest.raises(transit.TransitError):
        transit.call_transitous(FREIHEIT_22, KARL_MARX_ALLEE_3, transit.at(DATE, dt.time(8)))
    assert len(requests) == SOURCE_ATTEMPTS


def test_only_connections_from_the_time_on_count_the_fastest_of_each_departure():
    leave = transit.at(dt.date(2026, 10, 21), dt.time(7, 40))  # 05:40 in UTC

    def connection(start: str, minutes: int) -> transit.Connection:
        leaves = dt.datetime.fromisoformat(f"2026-10-21T{start}:00Z")
        return transit.Connection(leaves, minutes * 60)

    connections = [
        connection("05:39", 10),  # leaves before the user does
        connection("05:50", 40),
        connection("05:45", 30),
        connection("05:45", 20),  # the same departure, faster
        connection("06:10", 30),
        connection("06:20", 99),  # the fourth departure
    ]
    assert transit.find_durations(connections, leave) == [20 * 60, 40 * 60, 30 * 60]


@pytest.mark.parametrize(
    "date, day",
    [
        (dt.date(2026, 10, 13), dt.date(2026, 10, 14)),  # a Tuesday: the next day
        (dt.date(2026, 10, 14), dt.date(2026, 10, 21)),  # a Wednesday: a week later
        (dt.date(2025, 12, 20), dt.date(2026, 1, 7)),  # not 24 or 31 December, into the new year
        (dt.date(2030, 4, 29), dt.date(2030, 5, 8)),  # not Labour Day, Wednesday 1 May 2030
    ],
)
def test_the_journeys_are_on_the_first_wednesday_after_the_date_with_a_normal_timetable(date, day):
    assert transit.choose_day(date) == day


def test_a_time_in_winter_is_an_hour_later_in_utc_than_in_summer():
    winter = transit.at(dt.date(2026, 11, 4), dt.time(7, 40))
    summer = transit.at(dt.date(2026, 10, 21), dt.time(7, 40))
    assert winter.astimezone(dt.UTC).hour == 6 and summer.astimezone(dt.UTC).hour == 5
