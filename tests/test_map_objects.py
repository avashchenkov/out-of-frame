"""The map objects around a property, on recorded Overpass responses."""

import json

import httpx
import pytest

from evals.load import FIXTURES
from out_of_frame import map_objects
from out_of_frame.config import MAP_OBJECTS_PER_CATEGORY, SOURCE_ATTEMPTS
from out_of_frame.map_objects import (
    MapError,
    fetch_addresses,
    fetch_map_objects,
    group_into_objects,
)
from out_of_frame.state import Coordinates, MapObject

FREIHEIT_22 = Coordinates(lat=52.5292863, lon=13.2357896)


def read_fixture(name):
    return json.loads((FIXTURES / "overpass" / name).read_text(encoding="utf-8"))


def fake_overpass(monkeypatch, *answers) -> list[str]:
    """Overpass answers the requests in turn: a response to send as JSON, an HTTP status code
    to fail with, or an exception to raise. Returns the queries."""
    queries, answers = [], list(answers)

    def post(url, data, **kwargs):
        queries.append(data["data"])
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        request = httpx.Request("POST", url)
        if isinstance(answer, int):
            return httpx.Response(answer, request=request)
        return httpx.Response(200, json=answer, request=request)

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(map_objects.time, "sleep", lambda seconds: None)
    return queries


def find(objects, id):
    return next(map_object for map_object in objects if map_object.id == id)


def test_one_query_gets_the_nearest_objects_of_every_category(monkeypatch):
    queries = fake_overpass(monkeypatch, read_fixture("freiheit-22.json"))
    objects, source = fetch_map_objects(FREIHEIT_22)
    [query] = queries
    categories = [map_object.details["category"] for map_object in objects]
    # Of 29 industry elements and 37 road and rail elements, 28 and 6 objects.
    assert {name: categories.count(name) for name in set(categories)} == {
        "industry": MAP_OBJECTS_PER_CATEGORY,
        "road_rail": MAP_OBJECTS_PER_CATEGORY,
        "wastewater": 1,
    }
    industry = [o.distance_from_property_m for o in objects if o.details["category"] == "industry"]
    assert industry == [95, 118, 203, 217, 240]  # the nearest, nearest first
    assert "around:1500," in query and '["landuse"="industrial"]' in query
    assert '["highway"~"^(motorway|trunk)$"]' in query
    assert (source.id, source.kind) == ("overpass-1", "map")
    assert {map_object.source_id for map_object in objects} == {"overpass-1"}


def test_an_object_keeps_its_name_and_tags_and_has_no_addresses_yet(monkeypatch):
    fake_overpass(monkeypatch, read_fixture("freiheit-22.json"))
    objects, _ = fetch_map_objects(FREIHEIT_22)
    plant = find(objects, "osm-way-49572120")
    assert plant.name == "Müllverbrennungsanlage Ruhleben"
    assert plant.details["power"] == "plant" and plant.details["category"] == "industry"
    assert plant.addresses == []
    railway = find(objects, "osm-way-295391379")
    assert (railway.name, railway.details["railway"], railway.details["ref"]) == (
        None,
        "rail",
        "6107",
    )


def test_the_l1_object_is_measured_to_its_nearest_edge(monkeypatch):
    fake_overpass(monkeypatch, read_fixture("freiheit-22.json"))
    objects, _ = fetch_map_objects(FREIHEIT_22)
    assert abs(find(objects, "osm-way-985575964").distance_from_property_m - 218) <= 2  # L1


def square_around_freiheit_22(side_m: float, tags: dict) -> dict:
    """A closed way with the property at its centre."""
    d_lat, d_lon = side_m / 2 / 111_195, side_m / 2 / 67_700  # metres per degree there
    corners = [(-d_lat, -d_lon), (-d_lat, d_lon), (d_lat, d_lon), (d_lat, -d_lon), (-d_lat, -d_lon)]
    points = [{"lat": FREIHEIT_22.lat + lat, "lon": FREIHEIT_22.lon + lon} for lat, lon in corners]
    return {"type": "way", "id": 1, "geometry": points, "tags": tags}


def test_inside_an_area_the_distance_is_zero():
    area = square_around_freiheit_22(200, {"landuse": "industrial"})
    assert map_objects.measure_distance_m(FREIHEIT_22, area) == 0


def test_a_railway_loop_around_the_property_is_not_an_area():
    loop = square_around_freiheit_22(200, {"railway": "rail"})
    assert map_objects.measure_distance_m(FREIHEIT_22, loop) == pytest.approx(100, abs=2)


def test_a_relation_is_measured_to_its_edges_even_from_inside_its_hole():
    outer = square_around_freiheit_22(400, {})["geometry"]
    hole = square_around_freiheit_22(100, {})["geometry"]
    site = {
        "type": "relation",
        "tags": {"landuse": "industrial"},
        "members": [
            {"type": "way", "role": "outer", "geometry": outer},
            {"type": "way", "role": "inner", "geometry": hole},
        ],
    }
    assert map_objects.measure_distance_m(FREIHEIT_22, site) == pytest.approx(50, abs=2)


def test_a_relation_of_points_is_measured_to_the_nearest_one():
    north = {"type": "node", "lat": FREIHEIT_22.lat + 0.001, "lon": FREIHEIT_22.lon}
    site = {"type": "relation", "tags": {"power": "plant"}, "members": [north]}
    assert map_objects.measure_distance_m(FREIHEIT_22, site) == pytest.approx(111, abs=1)


def element(id: int, distance: float, **tags) -> MapObject:
    return MapObject(
        id=f"osm-way-{id}",
        name=tags.pop("name", None),
        details=tags | {"category": "road_rail"},
        addresses=[],
        coordinates=FREIHEIT_22,
        distance_from_property_m=distance,
        source_id="overpass-1",
    )


def test_elements_with_the_same_ref_are_one_object_the_nearest_of_them():
    far, near = (
        element(1, 90, railway="rail", ref="6107"),
        element(2, 67, railway="rail", ref="6107"),
    )
    assert group_into_objects([far, near]) == [near]


def test_unnamed_tracks_are_one_object_but_unnamed_sites_are_not():
    tracks = [element(1, 50, railway="rail", service="yard"), element(2, 60, railway="rail")]
    sites = [element(3, 70, landuse="industrial"), element(4, 80, landuse="industrial")]
    assert group_into_objects(tracks + sites) == [tracks[0], *sites]


def test_elements_with_the_same_name_are_one_object_whatever_their_refs():
    far = element(1, 90, landuse="industrial", name="Heizkraftwerk Reuter West", ref="B")
    near = element(2, 40, landuse="industrial", name="Heizkraftwerk Reuter West", ref="A")
    assert group_into_objects([far, near]) == [near]


def test_a_name_and_a_ref_that_read_the_same_are_two_objects():
    named, numbered = (
        element(1, 50, railway="rail", name="6107"),
        element(2, 60, railway="rail", ref="6107"),
    )
    assert group_into_objects([named, numbered]) == [named, numbered]


def test_a_road_and_a_railway_or_two_stages_are_never_one_object():
    road = element(1, 50, highway="motorway")
    rail = element(2, 60, railway="rail")
    proposed = element(3, 70, highway="proposed", proposed="motorway")
    built, planned = (
        element(4, 80, highway="motorway", ref="A 100"),
        element(5, 90, highway="proposed", proposed="motorway", ref="A 100"),
    )
    assert group_into_objects([road, rail, proposed, built, planned]) == [
        road,
        rail,
        proposed,
        built,
        planned,
    ]


def test_an_element_without_a_place_on_the_map_is_left_out(monkeypatch):
    count = {"type": "count"}
    nested = {"type": "relation", "id": 9, "tags": {"landuse": "industrial"}, "members": []}
    fake_overpass(monkeypatch, {"elements": [count, nested, count, count, count]})
    objects, _ = fetch_map_objects(FREIHEIT_22)
    assert objects == []


def test_a_point_is_measured_to_itself():
    node = {"type": "node", "lat": FREIHEIT_22.lat + 0.001, "lon": FREIHEIT_22.lon}
    assert map_objects.measure_distance_m(FREIHEIT_22, node) == pytest.approx(111, abs=1)


def test_the_addresses_inside_every_area_come_from_one_more_query(monkeypatch):
    fake_overpass(monkeypatch, read_fixture("freiheit-22.json"))
    objects, _ = fetch_map_objects(FREIHEIT_22)
    industry = [o for o in objects if o.details["category"] == "industry"]
    queries = fake_overpass(monkeypatch, read_fixture("freiheit-22-addresses.json"))
    addresses = fetch_addresses(industry)
    [query] = queries
    assert addresses["osm-way-23156479"] == [
        "Klärwerkstraße 1, 13597 Berlin",
        "Klärwerkstraße 1A, 13597 Berlin",
    ]
    assert addresses["osm-way-49572127"] == []  # an area with no addresses inside
    assert len(addresses) == 5 and "way(23156479);map_to_area" in query


def test_a_point_a_road_and_a_railway_have_no_addresses_and_need_no_query(monkeypatch):
    queries = fake_overpass(monkeypatch)
    node = {"type": "node", "id": 7, "lat": FREIHEIT_22.lat, "lon": FREIHEIT_22.lon}
    point = map_objects.build_map_object(node, "industry", FREIHEIT_22, "overpass-1")
    lines = [element(1, 50, highway="motorway"), element(2, 60, railway="rail")]
    assert fetch_addresses([point, *lines]) == {} and queries == []


def test_a_missing_part_of_an_address_is_left_out():
    tags = {"addr:street": "Klärwerkstraße", "addr:housenumber": "3"}
    assert map_objects.format_address(tags) == "Klärwerkstraße 3"


@pytest.mark.parametrize(
    "failure",
    [504, {"elements": [], "remark": "runtime error: Query timed out"}, httpx.ReadTimeout("slow")],
    ids=["busy", "cut off", "timeout"],
)
def test_overpass_is_tried_again_and_then_fails(monkeypatch, failure):
    queries = fake_overpass(monkeypatch, *[failure] * SOURCE_ATTEMPTS)
    with pytest.raises(MapError):
        fetch_map_objects(FREIHEIT_22)
    assert len(queries) == SOURCE_ATTEMPTS


def test_a_busy_overpass_is_tried_again(monkeypatch):
    queries = fake_overpass(monkeypatch, 429, read_fixture("freiheit-22.json"))
    objects, _ = fetch_map_objects(FREIHEIT_22)
    assert len(objects) == 11 and len(queries) == 2
