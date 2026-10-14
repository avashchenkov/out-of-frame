"""The map objects around the property, from Overpass: see docs/architecture.md#one-run and
docs/sources.md#overpass."""

import json
import math
import time
from itertools import pairwise

import httpx

from out_of_frame import research_scope
from out_of_frame.config import (
    MAP_OBJECTS_PER_CATEGORY,
    OVERPASS_URL,
    SOURCE_ATTEMPTS,
    USER_AGENT,
)
from out_of_frame.state import Coordinates, MapObject, Source

EARTH_RADIUS_M = 6_371_000


class MapError(Exception):
    """Overpass failed after its retries. The map part of the report is then missing, and the
    rest of the run goes on, see docs/architecture.md#failures."""


def fetch_map_objects(origin: Coordinates) -> tuple[list[MapObject], Source]:
    """The nearest objects of every category within the category's radius of the origin,
    without their addresses, and the Overpass response they come from."""
    categories = [c for c in research_scope.load().categories if c.source == "overpass"]
    query = "[out:json][timeout:90];"
    for category in categories:
        around = f"nwr(around:{category.radius_m},{origin.lat},{origin.lon})"
        union = "".join(f"{around}{build_tag_filter(tags)};" for tags in category.osm_tags)
        query += f"({union});out count;out geom;"  # the count marks where a category starts
    response = call_overpass(query)
    source = Source(
        id="overpass-1",
        kind="map",
        request=query,
        url=OVERPASS_URL,
        content=json.dumps(response, ensure_ascii=False),
    )
    objects: dict[str, MapObject] = {}
    for category, elements in zip(categories, split_by_count(response), strict=True):
        placed = [
            build_map_object(element, category.id, origin, source.id)
            for element in drop_parts(elements)
            if "lat" in element or "bounds" in element  # not a relation of relations
        ]
        for map_object in group_into_objects(placed)[:MAP_OBJECTS_PER_CATEGORY]:
            objects.setdefault(map_object.id, map_object)  # an element of two categories once
    return list(objects.values()), source


def drop_parts(elements: list[dict]) -> list[dict]:
    """The elements of one category without the unnamed ones inside the area of a larger one,
    such as a building inside the site it belongs to: the site stands for its parts. A named
    element is an object of its own, such as a factory inside an industrial area."""
    areas = [element for element in elements if is_area(element)]
    return [
        element
        for element in elements
        if "name" in element.get("tags", {})
        or not any(area is not element and lies_inside(element, area) for area in areas)
    ]


def is_area(element: dict) -> bool:
    """A closed way that is not a road or a railway, such as a site's outline."""
    tags = element.get("tags", {})
    if element["type"] != "way" or "highway" in tags or "railway" in tags:
        return False
    points = element.get("geometry") or []
    return len(points) > 3 and points[0] == points[-1]


def lies_inside(element: dict, area: dict) -> bool:
    """Whether the element's centre lies inside the area, which is the larger of the two."""
    if "lat" not in element and "bounds" not in element:
        return False
    if measure_bounds(element) >= measure_bounds(area):
        return False
    centre = find_centre(element)
    outline = [project(centre, (point["lat"], point["lon"])) for point in area["geometry"]]
    return contains_origin(outline)


def measure_bounds(element: dict) -> float:
    """The size of the element's bounds in square degrees; 0 for a node."""
    if "bounds" not in element:
        return 0.0
    bounds = element["bounds"]
    return (bounds["maxlat"] - bounds["minlat"]) * (bounds["maxlon"] - bounds["minlon"])


def group_into_objects(elements: list[MapObject]) -> list[MapObject]:
    """The objects that the elements of one category make, nearest first: elements of one
    group are one object, which is the nearest of them, see find_group."""
    objects: dict[tuple, MapObject] = {}
    for element in sorted(elements, key=lambda element: element.distance_from_property_m):
        objects.setdefault(find_group(element), element)
    return list(objects.values())


def find_group(element: MapObject) -> tuple:
    """Elements with the same name, or without a name the same ref, such as a road number, and
    at the same stage are one object; a road and a railway never are. Road elements, or rail
    elements, of one stage with neither are one object too, such as service tracks; any other
    element without a name is an object of its own."""
    tags = element.details
    kind = "road" if "highway" in tags else "rail" if "railway" in tags else None
    label = ("name", element.name) if element.name else ("ref", tags.get("ref"))
    if label == ("ref", None) and kind is None:
        return (element.id,)
    return (kind, find_stage(tags), *label)


def find_stage(tags: dict[str, str]) -> str:
    """construction or proposed for a road or a railway tagged so, otherwise built."""
    stages = [tags.get(key) for key in ("highway", "railway")]
    return next((stage for stage in stages if stage in ("construction", "proposed")), "built")


def fetch_addresses(objects: list[MapObject]) -> dict[str, list[str]]:
    """The street addresses of the buildings inside each object's area, by which an unnamed
    object can be found on the web, by the object's ID, from one query. A single point, a road
    and a railway have none, so they are not asked for."""
    areas = [
        map_object
        for map_object in objects
        if map_object.id.startswith(("osm-way-", "osm-relation-"))  # see build_map_object
        and not {"highway", "railway"} & map_object.details.keys()
    ]
    if not areas:
        return {}
    query = "[out:json][timeout:90];"
    for map_object in areas:
        _, osm_type, osm_id = map_object.id.split("-")
        query += f'{osm_type}({osm_id});map_to_area->.a;nwr(area.a)["addr:housenumber"];'
        query += "out count;out tags;"  # the count marks where an object's addresses start
    groups = split_by_count(call_overpass(query))
    return {
        map_object.id: sorted({format_address(element["tags"]) for element in elements})
        for map_object, elements in zip(areas, groups, strict=True)
    }


def split_by_count(response: dict) -> list[list[dict]]:
    """The elements of a response, split at each count: the output of each part of a query."""
    groups: list[list[dict]] = []
    for element in response["elements"]:
        if element["type"] == "count":
            groups.append([])
        else:
            groups[-1].append(element)
    return groups


def build_tag_filter(tags: dict[str, str | list[str]]) -> str:
    """Overpass QL for the tags: {"k": "v", "k2": ["a", "b"]} -> ["k"="v"]["k2"~"^(a|b)$"]"""
    return "".join(
        f'["{key}"~"^({"|".join(value)})$"]' if isinstance(value, list) else f'["{key}"="{value}"]'
        for key, value in tags.items()
    )


def build_map_object(
    element: dict, category: str, origin: Coordinates, source_id: str
) -> MapObject:
    tags = element.get("tags", {})
    return MapObject(
        id=f"osm-{element['type']}-{element['id']}",
        name=tags.get("name"),
        details=tags | {"category": category},
        addresses=[],
        coordinates=find_centre(element),
        distance_from_property_m=round(measure_distance_m(origin, element)),
        source_id=source_id,
    )


def find_centre(element: dict) -> Coordinates:
    """A node's own point; for a way or a relation, the centre of its bounds."""
    if element["type"] == "node":
        return Coordinates(lat=element["lat"], lon=element["lon"])
    bounds = element["bounds"]
    return Coordinates(
        lat=(bounds["minlat"] + bounds["maxlat"]) / 2,
        lon=(bounds["minlon"] + bounds["maxlon"]) / 2,
    )


def measure_distance_m(origin: Coordinates, element: dict) -> float:
    """Metres from the origin to the element's nearest edge, 0 inside a closed way.

    A road or a railway that closes a loop is not an area. A relation, such as a site with a
    hole in it, is measured to its edges even from inside, so that a hole does not count as
    inside; a property is rarely inside an industrial site or an airport."""
    lines = [[project(origin, point) for point in line] for line in read_lines(element)]
    tags = element.get("tags", {})
    if element["type"] == "way" and "highway" not in tags and "railway" not in tags:
        [outline] = lines
        if outline[0] == outline[-1] and contains_origin(outline):
            return 0.0
    return min(measure_distance_to_line(line) for line in lines)


def read_lines(element: dict) -> list[list[tuple[float, float]]]:
    """The element's points as lines of (lat, lon): a node is a line of one point, a way one
    line, and a relation one line for each member way and each member node, or its centre if
    it has neither."""
    if element["type"] == "node":
        return [[(element["lat"], element["lon"])]]
    if element["type"] == "way":
        return [[(point["lat"], point["lon"]) for point in element["geometry"]]]
    lines = [
        [(point["lat"], point["lon"]) for point in member["geometry"]]
        if member["type"] == "way"
        else [(member["lat"], member["lon"])]
        for member in element["members"]
        if member["type"] in ("way", "node")
    ]
    if lines:
        return lines
    centre = find_centre(element)
    return [[(centre.lat, centre.lon)]]


def project(origin: Coordinates, point: tuple[float, float]) -> tuple[float, float]:
    """The point in metres east and north of the origin. Flat, which is close enough within a
    few kilometres."""
    lat, lon = point
    east = math.radians(lon - origin.lon) * EARTH_RADIUS_M * math.cos(math.radians(origin.lat))
    north = math.radians(lat - origin.lat) * EARTH_RADIUS_M
    return east, north


def measure_distance_to_line(line: list[tuple[float, float]]) -> float:
    """Metres from the origin, at (0, 0), to the nearest point of the line."""
    if len(line) == 1:
        return math.hypot(*line[0])
    distances = []
    for (x1, y1), (x2, y2) in pairwise(line):
        dx, dy = x2 - x1, y2 - y1
        # The share of the segment, from 0 to 1, at the point nearest to the origin.
        t = max(0.0, min(1.0, -(x1 * dx + y1 * dy) / (dx * dx + dy * dy or 1)))
        distances.append(math.hypot(x1 + t * dx, y1 + t * dy))
    return min(distances)


def contains_origin(polygon: list[tuple[float, float]]) -> bool:
    """Whether the closed polygon contains the origin, at (0, 0): a ray from it to the east
    crosses the edges an odd number of times."""
    inside = False
    for (x1, y1), (x2, y2) in pairwise(polygon):
        if (y1 > 0) != (y2 > 0) and x1 + (0 - y1) * (x2 - x1) / (y2 - y1) > 0:
            inside = not inside
    return inside


def format_address(tags: dict[str, str]) -> str:
    """Such as Klärwerkstraße 3, 13597 Berlin; a missing part is left out."""
    street = " ".join(filter(None, [tags.get("addr:street"), tags.get("addr:housenumber")]))
    place = " ".join(filter(None, [tags.get("addr:postcode"), tags.get("addr:city")]))
    return ", ".join(filter(None, [street, place]))


def call_overpass(query: str) -> dict:
    """Overpass's answer to the query, tried again on any failure. The public instance is often
    busy, so it waits longer between tries than for other services."""
    for attempt in range(1, SOURCE_ATTEMPTS + 1):
        try:
            response = httpx.post(
                OVERPASS_URL, data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=120
            )
            response.raise_for_status()
            answer = response.json()
            if "remark" in answer:  # a timeout or an error, with the elements cut off
                raise ValueError(answer["remark"])
            return answer
        except (httpx.HTTPError, ValueError) as error:  # ValueError: also a cut-off JSON
            if attempt == SOURCE_ATTEMPTS:
                raise MapError(f"{SOURCE_ATTEMPTS} tries failed: {error!r}") from error
            time.sleep(15 * attempt)  # it often answers 429 or 504 for a while
    raise ValueError("OUT_OF_FRAME_SOURCE_ATTEMPTS must be at least 1")
