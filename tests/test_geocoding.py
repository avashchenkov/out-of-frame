"""Geocoding on recorded Nominatim responses."""

import copy
import json

import httpx
import pytest

from evals.load import FIXTURES
from out_of_frame import geocoding
from out_of_frame.config import SOURCE_ATTEMPTS, USER_AGENT
from out_of_frame.geocoding import GeocodingError
from out_of_frame.state import Address, Coordinates

FREIHEIT_22 = Coordinates(lat=52.5292863, lon=13.2357896)


def read_fixture(name):
    return json.loads((FIXTURES / "nominatim" / name).read_text(encoding="utf-8"))


def fake_nominatim(monkeypatch, answer) -> list[dict]:
    """Nominatim answers every request with the answer: results to send as JSON, raw bytes, or
    an exception to raise. Returns the keyword arguments of each request."""
    requests = []

    def get(url, **kwargs):
        requests.append(kwargs)
        if isinstance(answer, Exception):
            raise answer
        content = answer if isinstance(answer, bytes) else json.dumps(answer).encode()
        return httpx.Response(200, content=content, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(geocoding.time, "sleep", lambda seconds: None)
    return requests


def geocode(
    monkeypatch, results, text="Freiheit 22, 13597 Berlin", berlin_only=True
) -> tuple[Address, str | None]:
    """The geocoded address and why it has no coordinates, if it has none: the property's, by
    default, or with berlin_only False a destination's."""
    fake_nominatim(monkeypatch, results)
    address, source = geocoding.geocode(text, "nominatim-1", berlin_only=berlin_only)
    return address, geocoding.explain(address, source, berlin_only=berlin_only)


def test_one_building_in_berlin_gives_its_coordinates_and_the_response(monkeypatch):
    results = read_fixture("freiheit-22.json")
    requests = fake_nominatim(monkeypatch, results)
    address, source = geocoding.geocode(
        "Freiheit 22, 13597 Berlin", "nominatim-1", berlin_only=True
    )
    assert address == Address(
        text="Freiheit 22, 13597 Berlin", coordinates=FREIHEIT_22, source_id="nominatim-1"
    )
    assert source.id == "nominatim-1" and source.kind == "geocoding"
    assert source.request == "Freiheit 22, 13597 Berlin" and json.loads(source.content) == results
    assert geocoding.explain(address, source, berlin_only=True) is None
    [request] = requests
    # Without addressdetails, a match has no address to check.
    params = {"q": "Freiheit 22, 13597 Berlin", "format": "jsonv2", "addressdetails": 1}
    assert request["params"] == params
    assert request["headers"] == {"User-Agent": USER_AGENT}


def test_a_street_alone_gives_no_coordinates(monkeypatch):
    address, reason = geocode(monkeypatch, read_fixture("freiheit-street.json"), "Freiheit, Berlin")
    assert address.coordinates is None and address.source_id == "nominatim-1"
    assert reason == "'Freiheit, Berlin' matches only a street or an area, not one building."


def test_one_building_among_streets_gives_its_coordinates(monkeypatch):
    results = read_fixture("freiheit-street.json") + read_fixture("freiheit-22.json")
    address, reason = geocode(monkeypatch, results, "Freiheit 22, Berlin")
    assert address.coordinates == FREIHEIT_22 and reason is None


def test_several_buildings_give_no_coordinates_and_are_named_for_the_user(monkeypatch):
    address, reason = geocode(monkeypatch, read_fixture("hauptstrasse-1.json"), "Hauptstraße 1")
    assert address.coordinates is None
    assert reason == (
        "Several buildings in Berlin match 'Hauptstraße 1': "
        "Hauptstraße 1, 10317 Berlin (Rummelsburg); Hauptstraße 1, 13591 Berlin (Staaken); "
        "Hauptstraße 1, 13159 Berlin (Blankenfelde); "
        "Hauptstraße 1, 13055 Berlin (Alt-Hohenschönhausen)."
    )


def test_a_building_without_a_postcode_is_named_with_its_district(monkeypatch):
    rummelsburg, staaken, *_ = read_fixture("hauptstrasse-1.json")
    del staaken["address"]["postcode"]
    _, reason = geocode(monkeypatch, [rummelsburg, staaken], "Hauptstraße 1")
    assert reason == (
        "Several buildings in Berlin match 'Hauptstraße 1': "
        "Hauptstraße 1, 10317 Berlin (Rummelsburg); Hauptstraße 1, Staaken, Berlin."
    )


def test_buildings_without_a_postcode_in_two_districts_are_two_buildings(monkeypatch):
    rummelsburg, staaken, *_ = read_fixture("hauptstrasse-1.json")
    for building in rummelsburg, staaken:
        del building["address"]["postcode"]
    del staaken["address"]["suburb"]  # its district is then only in city_district
    address, reason = geocode(monkeypatch, [rummelsburg, staaken], "Hauptstraße 1")
    assert address.coordinates is None
    assert reason == (
        "Several buildings in Berlin match 'Hauptstraße 1': "
        "Hauptstraße 1, Rummelsburg, Berlin; Hauptstraße 1, Spandau, Berlin."
    )


def test_one_building_named_with_two_districts_is_one_building(monkeypatch):
    [point] = read_fixture("freiheit-22.json")
    outline = copy.deepcopy(point)
    outline["address"]["suburb"] = "Wilhelmstadt"  # the postcode is the same
    address, reason = geocode(monkeypatch, [point, outline])
    assert address.coordinates == FREIHEIT_22 and reason is None


def test_an_address_point_and_its_building_outline_are_one_building(monkeypatch):
    [point] = read_fixture("freiheit-22.json")
    outline = point | {
        "osm_type": "way",
        "category": "building",
        "lat": "52.5293",
        "lon": "13.2358",
    }
    address, _ = geocode(monkeypatch, [point, outline])
    assert address.coordinates is not None


def test_a_building_in_berlin_is_kept_after_one_with_the_same_address_elsewhere(monkeypatch):
    [berlin] = read_fixture("freiheit-22.json")
    del berlin["address"]["postcode"]
    elsewhere = copy.deepcopy(berlin)
    elsewhere["address"]["ISO3166-2-lvl4"] = "DE-BB"  # Brandenburg
    address, reason = geocode(monkeypatch, [elsewhere, berlin], "Freiheit 22")
    assert address.coordinates == FREIHEIT_22 and reason is None


def test_a_building_with_another_postcode_gives_no_coordinates(monkeypatch):
    # Nominatim's only match is the same street and number in Frohnau, not in Moabit.
    text = "Huttenstraße 10, 10553 Berlin"
    address, reason = geocode(monkeypatch, read_fixture("huttenstrasse-10.json"), text)
    assert address.coordinates is None
    assert reason == (
        "'Huttenstraße 10, 10553 Berlin' matches no building in Berlin with its postcode, only: "
        "Huttenstraße 10, 13465 Berlin (Frohnau)."
    )


@pytest.mark.parametrize("postcode", ["14109", None])
def test_the_e7_postcode_selects_one_of_two_different_places(monkeypatch, postcode):
    results = read_fixture("e7-teltower-strasse-31.json")
    # The Spandau result goes first so the test also rejects merging or taking the first hit.
    text = "Teltower Straße 31, " + (f"{postcode} " if postcode else "") + "Berlin"
    address, reason = geocode(monkeypatch, list(reversed(results)), text)
    if postcode:
        assert address.coordinates == Coordinates(lat=52.3900433, lon=13.1281581)
        assert reason is None
    else:
        assert address.coordinates is None
        assert "Several buildings" in reason and "13597" in reason and "14109" in reason


def test_a_building_outside_berlin_gives_no_coordinates(monkeypatch):
    [building] = read_fixture("freiheit-22.json")
    building["address"]["ISO3166-2-lvl4"] = "DE-BB"  # Brandenburg
    address, reason = geocode(monkeypatch, [building])
    assert address.coordinates is None
    assert reason == "'Freiheit 22, 13597 Berlin' is outside Berlin, and only Berlin is checked."


def test_no_match_gives_no_coordinates(monkeypatch):
    address, reason = geocode(monkeypatch, [], "Nowhere 1")
    assert address.coordinates is None and reason == "No place in Berlin matches 'Nowhere 1'."


@pytest.mark.parametrize(
    "text, query",
    [
        ("Hauptstraße 1", "Hauptstraße 1, Berlin"),
        ("Berliner Straße 5", "Berliner Straße 5, Berlin"),
        ("Freiheit 22, 13597 berlin", "Freiheit 22, 13597 berlin"),
    ],
)
def test_the_city_is_added_to_an_address_that_does_not_name_it(monkeypatch, text, query):
    requests = fake_nominatim(monkeypatch, [])
    _, source = geocoding.geocode(text, "nominatim-1", berlin_only=True)
    assert requests[0]["params"]["q"] == query and source.request == query


@pytest.mark.parametrize(
    "answer", [httpx.ConnectTimeout("no answer"), b'[{"lat": '], ids=["timeout", "cut off"]
)
def test_nominatim_is_tried_again_and_then_fails(monkeypatch, answer):
    requests = fake_nominatim(monkeypatch, answer)
    with pytest.raises(GeocodingError):
        geocoding.geocode("Freiheit 22, 13597 Berlin", "nominatim-1", berlin_only=True)
    assert len(requests) == SOURCE_ATTEMPTS


POTSDAM = "Am Kanal 47, 14467 Potsdam"


def test_a_destination_outside_berlin_gives_its_coordinates_without_berlin_in_the_query(
    monkeypatch,
):
    requests = fake_nominatim(monkeypatch, read_fixture("am-kanal-47-potsdam.json"))
    address, source = geocoding.geocode(POTSDAM, "nominatim-1", berlin_only=False)
    assert address.coordinates == Coordinates(lat=52.3971923, lon=13.0592866)
    assert requests[0]["params"]["q"] == POTSDAM and source.request == POTSDAM
    assert geocoding.explain(address, source, berlin_only=False) is None


def test_the_buildings_that_match_a_destination_are_named_with_their_town(monkeypatch):
    potsdam = read_fixture("am-kanal-47-potsdam.json")[0]
    [berlin] = read_fixture("freiheit-22.json")
    elsewhere = copy.deepcopy(potsdam)
    elsewhere["address"] |= {"postcode": "15711", "city": "Königs Wusterhausen"}
    del elsewhere["address"]["suburb"]
    address, reason = geocode(monkeypatch, [potsdam, berlin, elsewhere], "Am Kanal 47", False)
    assert address.coordinates is None
    assert reason == (
        "Several buildings match 'Am Kanal 47': "
        "Am Kanal 47, 14467 Potsdam (Historische Innenstadt); "
        "Freiheit 22, 13597 Berlin (Spandau); Am Kanal 47, 15711 Königs Wusterhausen."
    )


def test_buildings_with_one_postcode_in_two_towns_are_two_buildings(monkeypatch):
    potsdam = read_fixture("am-kanal-47-potsdam.json")[0]
    village = copy.deepcopy(potsdam)
    village["address"]["city"] = "Geltow"  # the same street, number and postcode
    del village["address"]["suburb"]
    address, reason = geocode(monkeypatch, [potsdam, village], POTSDAM, berlin_only=False)
    assert address.coordinates is None
    assert reason == (
        "Several buildings match 'Am Kanal 47, 14467 Potsdam': "
        "Am Kanal 47, 14467 Potsdam (Historische Innenstadt); Am Kanal 47, 14467 Geltow."
    )


@pytest.mark.parametrize(
    "results, reason",
    [
        ([], "No place matches 'Am Kanal 47, 14467 Potsdam'."),
        (
            read_fixture("freiheit-street.json"),
            "'Am Kanal 47, 14467 Potsdam' matches only a street or an area, not one building.",
        ),
        (
            read_fixture("freiheit-22.json"),
            "'Am Kanal 47, 14467 Potsdam' matches no building with its postcode, only: "
            "Freiheit 22, 13597 Berlin (Spandau).",
        ),
    ],
    ids=["no match", "a street", "another postcode"],
)
def test_a_destination_without_coordinates_is_explained_without_berlin(
    monkeypatch, results, reason
):
    address, found = geocode(monkeypatch, results, POTSDAM, berlin_only=False)
    assert address.coordinates is None and found == reason


def test_each_request_to_nominatim_waits_a_second_after_the_last_one(monkeypatch):
    fake_nominatim(monkeypatch, [])
    clock, waits = [100.0], []
    monkeypatch.setattr(geocoding.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(geocoding.time, "sleep", waits.append)
    monkeypatch.setattr(geocoding, "last_request_at", float("-inf"))
    geocoding.call_nominatim("Freiheit 22")
    clock[0] = 100.25
    geocoding.call_nominatim("Freiheit 22")
    assert waits == [0.0, 0.75]
