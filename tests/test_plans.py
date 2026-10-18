"""The development plans around the property, on a recorded B-Plan WFS response."""

import json
import math

import httpx
import pytest

from evals.load import FIXTURES
from out_of_frame import plans
from out_of_frame.config import SOURCE_ATTEMPTS, USER_AGENT
from out_of_frame.plans import PlansError, fetch_plans
from out_of_frame.state import Coordinates

FREIHEIT_22 = Coordinates(lat=52.5292863, lon=13.2357896)
RECORDED = json.loads((FIXTURES / "bplan" / "freiheit-22.json").read_text(encoding="utf-8"))


def fake_wfs(monkeypatch, answer=None) -> list[dict]:
    """The WFS answers each layer from the recording around Freiheit 22, or raises answer if it
    is an exception. Returns the parameters of each request."""
    requests = []

    def get(url, **kwargs):
        requests.append(kwargs)
        if isinstance(answer, Exception):
            raise answer
        content = json.dumps(RECORDED[kwargs["params"]["typeNames"]]).encode()
        return httpx.Response(200, content=content, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(plans.time, "sleep", lambda seconds: None)
    return requests


def test_the_nearest_plans_within_the_radius_are_kept_nearest_first(monkeypatch):
    fake_wfs(monkeypatch)
    found, source = fetch_plans(FREIHEIT_22)
    # Six plans reach into the 500 m circle; the sixth, VIII-250 at 416 m, is over the limit
    # of five. The WFS returns three more whose shapes lie outside the circle, such as VII-A
    # at 1289 m.
    assert [(plan.name, plan.rounded_distance_m()) for plan in found] == [
        ("Bebauungsplan VIII-129", 217),
        ("Bebauungsplan VIII-286", 228),
        ("Bebauungsplan 5-1VE", 264),
        ("Bebauungsplan VIII-B6", 315),
        ("Bebauungsplan VIII-145", 343),
    ]
    assert source.id == "bplan-wfs-1" and source.kind == "plans"
    assert json.loads(source.content) == RECORDED


def test_the_plans_outside_the_circle_are_dropped(monkeypatch):
    fake_wfs(monkeypatch)
    monkeypatch.setattr(plans, "PLANS", 20)  # so that only the circle limits them
    found, _ = fetch_plans(FREIHEIT_22)
    assert [plan.name for plan in found][-2:] == [
        "Bebauungsplan VIII-145",
        "Bebauungsplan VIII-250",
    ]
    assert max(plan.rounded_distance_m() for plan in found) == 416  # not VII-A at 1289 m


def test_a_plan_keeps_its_legal_status_and_what_it_allows(monkeypatch):
    fake_wfs(monkeypatch)
    found, _ = fetch_plans(FREIHEIT_22)
    plan = next(plan for plan in found if plan.name == "Bebauungsplan VIII-B6")
    assert plan.id == "bplan-0508000B06" and plan.addresses == []
    assert plan.details["category"] == "planned_objects"
    assert plan.details["bp_rechtsstand"] == "In Kraft getreten"
    assert plan.details["inhalt"] == "Gewerbegebiet, Industriegebiet"
    assert plan.details["scan_www"].endswith("/08__b6.pdf")  # the plan itself, as a scan
    assert plan.details["festsg_am"] and plan.details["fsg_gvbl_n"]  # every field, as it came
    assert None not in plan.details.values() and "" not in plan.details.values()
    assert plan.source_id == "bplan-wfs-1"


def test_each_layer_is_asked_for_the_square_around_the_circle(monkeypatch):
    requests = fake_wfs(monkeypatch)
    fetch_plans(FREIHEIT_22)
    assert [request["params"]["typeNames"] for request in requests] == [
        "bplan:a_bp_iv",
        "bplan:b_bp_fs",
    ]
    south, west, north, east, crs = requests[0]["params"]["bbox"].split(",")
    assert crs == "urn:ogc:def:crs:EPSG::4326"
    assert float(south) < FREIHEIT_22.lat < float(north)
    assert float(west) < FREIHEIT_22.lon < float(east)
    assert (float(north) - float(south)) * 111_195 == pytest.approx(1000, abs=1)  # 2 × 500 m
    width = (float(east) - float(west)) * 111_195 * math.cos(math.radians(FREIHEIT_22.lat))
    assert width == pytest.approx(1000, abs=1)
    assert requests[0]["params"]["srsName"] == "EPSG:4326"
    assert requests[0]["headers"] == {"User-Agent": USER_AGENT}


def square(side_m: float, east_m: float = 0) -> list[list[float]]:
    """A ring of [lon, lat] around a point east of Freiheit 22, as GeoJSON has it."""
    half, centre = side_m / 2 / 111_195, FREIHEIT_22.lon + east_m / 67_700
    lats = FREIHEIT_22.lat - half, FREIHEIT_22.lat + half
    lons = centre - half * 1.64, centre + half * 1.64  # a degree of longitude is shorter here
    return [
        [lons[0], lats[0]],
        [lons[1], lats[0]],
        [lons[1], lats[1]],
        [lons[0], lats[1]],
        [lons[0], lats[0]],
    ]


def test_inside_a_plan_the_distance_is_0_but_not_inside_its_hole():
    plan = {"type": "Polygon", "coordinates": [square(400)]}
    assert plans.measure_distance_m(FREIHEIT_22, plan) == 0
    holed = {"type": "Polygon", "coordinates": [square(400), square(100)]}
    assert plans.measure_distance_m(FREIHEIT_22, holed) == pytest.approx(50, abs=1)
    parts = {
        "type": "MultiPolygon",
        "coordinates": [[square(100, east_m=1000)], [square(100, east_m=300)]],
    }
    assert plans.measure_distance_m(FREIHEIT_22, parts) == pytest.approx(250, abs=1)


def test_a_plan_given_twice_is_one_object_at_its_nearest_part(monkeypatch):
    def feature(geometry) -> dict:
        return {
            "type": "Feature",
            "properties": {"planid": "1", "planname": "X"},
            "geometry": geometry,
        }

    far, near = (
        {"type": "Polygon", "coordinates": [square(100, east_m=east_m)]} for east_m in (400, 150)
    )
    answer = {"type": "FeatureCollection", "features": [feature(far), feature(near), feature(None)]}
    monkeypatch.setattr(plans, "call_wfs", lambda layer, bbox: answer)  # in both layers too
    found, _ = fetch_plans(FREIHEIT_22)
    assert [plan.id for plan in found] == ["bplan-1"]  # a part without a shape is left out
    assert found[0].distance_from_property_m == pytest.approx(100, abs=1)


def test_the_wfs_is_tried_again_and_then_fails(monkeypatch):
    requests = fake_wfs(monkeypatch, httpx.ConnectTimeout("no answer"))
    with pytest.raises(PlansError):
        fetch_plans(FREIHEIT_22)
    assert len(requests) == SOURCE_ATTEMPTS
