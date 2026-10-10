"""Geocoding on recorded Nominatim responses."""

import json

import httpx
import pytest

from evals.load import FIXTURES
from out_of_frame import geocoding
from out_of_frame.config import SOURCE_ATTEMPTS, USER_AGENT
from out_of_frame.geocoding import GeocodingError, geocode
from out_of_frame.state import Coordinates

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


def test_one_building_in_berlin_gives_its_coordinates(monkeypatch):
    requests = fake_nominatim(monkeypatch, read_fixture("freiheit-22.json"))
    assert geocode("Freiheit 22, 13597 Berlin") == FREIHEIT_22
    [request] = requests
    # Without addressdetails, a match has no address to check.
    params = {"q": "Freiheit 22, 13597 Berlin", "format": "jsonv2", "addressdetails": 1}
    assert request["params"] == params
    assert request["headers"] == {"User-Agent": USER_AGENT}


def test_a_street_alone_gives_no_coordinates(monkeypatch):
    fake_nominatim(monkeypatch, read_fixture("freiheit-street.json"))
    assert geocode("Freiheit, Berlin") is None


def test_one_building_among_streets_gives_its_coordinates(monkeypatch):
    results = read_fixture("freiheit-street.json") + read_fixture("freiheit-22.json")
    fake_nominatim(monkeypatch, results)
    assert geocode("Freiheit 22, Berlin") == FREIHEIT_22


def test_several_buildings_give_no_coordinates(monkeypatch):
    fake_nominatim(monkeypatch, read_fixture("hauptstrasse-1.json"))
    assert geocode("Hauptstraße 1, Berlin") is None


def test_an_address_point_and_its_building_outline_are_one_building(monkeypatch):
    [point] = read_fixture("freiheit-22.json")
    outline = point | {
        "osm_type": "way",
        "category": "building",
        "lat": "52.5293",
        "lon": "13.2358",
    }
    fake_nominatim(monkeypatch, [point, outline])
    assert geocode("Freiheit 22, 13597 Berlin") is not None


def test_a_building_outside_berlin_gives_no_coordinates(monkeypatch):
    [building] = read_fixture("freiheit-22.json")
    building["address"]["ISO3166-2-lvl4"] = "DE-BB"  # Brandenburg
    fake_nominatim(monkeypatch, [building])
    assert geocode("Freiheit 22, 13597 Berlin") is None


@pytest.mark.parametrize(
    "answer", [httpx.ConnectTimeout("no answer"), b'[{"lat": '], ids=["timeout", "cut off"]
)
def test_nominatim_is_tried_again_and_then_fails(monkeypatch, answer):
    requests = fake_nominatim(monkeypatch, answer)
    with pytest.raises(GeocodingError):
        geocode("Freiheit 22, 13597 Berlin")
    assert len(requests) == SOURCE_ATTEMPTS
