"""The development plans around the property, from the Berlin B-Plan WFS: see
docs/architecture.md#one-run and docs/sources.md#berlin-b-plan-wfs."""

import json
import math
import time

import httpx

from out_of_frame import research_scope
from out_of_frame.config import BPLAN_WFS_URL, PLANS, SOURCE_ATTEMPTS, USER_AGENT
from out_of_frame.map_objects import (
    contains_origin,
    measure_distance_to_line,
    project,
)
from out_of_frame.state import Coordinates, MapObject, Source


class PlansError(Exception):
    """The B-Plan WFS failed after its retries. The plans part of the report is then missing,
    and the rest of the run goes on, see docs/architecture.md#failures."""


def fetch_plans(origin: Coordinates) -> tuple[list[MapObject], Source]:
    """The nearest plans within the category's radius of the origin, one object per plan, and
    the WFS responses they come from. The WFS filters only by a rectangle, so code asks for the
    square around the circle and drops the plans outside it."""
    [category] = [c for c in research_scope.load().categories if c.source == "bplan_wfs"]
    bbox = build_bbox(origin, category.radius_m)
    responses = {layer: call_wfs(layer, bbox) for layer in category.wfs_feature_types}
    source = Source(
        id="bplan-wfs-1",
        kind="plans",
        request=json.dumps({"layers": category.wfs_feature_types, "bbox": bbox}),
        url=BPLAN_WFS_URL,
        content=json.dumps(responses, ensure_ascii=False),
    )
    parts = [
        build_plan(feature, category.id, origin, source.id)
        for response in responses.values()
        for feature in response["features"]
        if feature.get("geometry") is not None
    ]
    plans: dict[str, MapObject] = {}
    for plan in sorted(parts, key=lambda plan: plan.distance_from_property_m):
        if plan.distance_from_property_m <= category.radius_m:
            plans.setdefault(plan.id, plan)  # a plan given twice is one object, at its nearest
    return list(plans.values())[:PLANS], source


def build_bbox(origin: Coordinates, radius_m: float) -> str:
    """The square around the circle, as the WFS takes it in EPSG:4326: south, west, north,
    east, then the coordinate system."""
    dlat = math.degrees(radius_m / 6_371_000)
    dlon = dlat / math.cos(math.radians(origin.lat))
    corners = [origin.lat - dlat, origin.lon - dlon, origin.lat + dlat, origin.lon + dlon]
    return ",".join(f"{value:.6f}" for value in corners) + ",urn:ogc:def:crs:EPSG::4326"


def build_plan(feature: dict, category: str, origin: Coordinates, source_id: str) -> MapObject:
    fields = feature["properties"]
    # The fields as the WFS gives them, such as its legal status, bp_rechtsstand, and for a plan
    # in force what it allows, inhalt; an empty field is left out.
    details = {key: value for key, value in fields.items() if value not in (None, "")}
    return MapObject(
        id=f"bplan-{fields['planid']}",
        name=f"Bebauungsplan {fields['planname']}",
        details=details | {"category": category},
        addresses=[],  # a plan is found on the web by its name, see docs/architecture.md
        coordinates=find_centre(feature["geometry"]),
        distance_from_property_m=measure_distance_m(origin, feature["geometry"]),
        source_id=source_id,
    )


def read_polygons(geometry: dict) -> list[list[list[tuple[float, float]]]]:
    """The polygons of a GeoJSON Polygon or MultiPolygon, each a list of rings of (lat, lon):
    the outline first, then its holes."""
    polygons = geometry["coordinates"]
    if geometry["type"] == "Polygon":
        polygons = [polygons]
    return [[[(lat, lon) for lon, lat, *_ in ring] for ring in polygon] for polygon in polygons]


def measure_distance_m(origin: Coordinates, geometry: dict) -> float:
    """Metres from the origin to the plan's nearest edge, 0 inside the plan but not in a hole."""
    rings = []
    for polygon in read_polygons(geometry):
        outline, *holes = [[project(origin, point) for point in ring] for ring in polygon]
        if contains_origin(outline) and not any(contains_origin(hole) for hole in holes):
            return 0.0
        rings += [outline, *holes]
    return min(measure_distance_to_line(ring) for ring in rings)


def find_centre(geometry: dict) -> Coordinates:
    """The centre of the plan's bounds."""
    points = [point for polygon in read_polygons(geometry) for ring in polygon for point in ring]
    lats, lons = [lat for lat, _ in points], [lon for _, lon in points]
    return Coordinates(lat=(min(lats) + max(lats)) / 2, lon=(min(lons) + max(lons)) / 2)


def call_wfs(layer: str, bbox: str) -> dict:
    """The plans of one layer in the rectangle, as GeoJSON in EPSG:4326, tried again on any
    failure. The WFS takes only one layer a request."""
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": layer,
        "bbox": bbox,
        "srsName": "EPSG:4326",  # longitude first, as GeoJSON has it
        "outputFormat": "application/json",
    }
    for attempt in range(1, SOURCE_ATTEMPTS + 1):
        try:
            response = httpx.get(
                BPLAN_WFS_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=60
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:  # ValueError: also a cut-off JSON
            if attempt == SOURCE_ATTEMPTS:
                raise PlansError(f"{SOURCE_ATTEMPTS} tries failed: {error!r}") from error
            time.sleep(attempt)
    raise ValueError("OUT_OF_FRAME_SOURCE_ATTEMPTS must be at least 1")
