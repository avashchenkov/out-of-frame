"""Labels for an end-to-end address, see docs/eval-architecture.md#ground-truth-labels.

Record the address, the map and the plans there as fixtures, and print a label for each object
the agent can see, with its ID, category, coordinates and tolerance, for a person or a model to
fill in its type, status, page and search. What the agent sees of the object, the addresses
inside its area included, is printed above each label:

    uv run python -m evals.label "Freiheit 22, 13597 Berlin" e1-freiheit-22

Check that each scored label's search finds its page on Tavily, as the agent would search, and
that the page of a label without a search is linked in its object's recorded data:

    uv run --env-file .env python -m evals.label --check evals/tasks/e1.yaml
"""

import argparse
import json
import math
import sys
from pathlib import Path

from evals.graders.end_to_end import AddressLabel, ExpectedRun
from evals.load import find_recordings, load
from out_of_frame import geocoding, map_objects, plans
from out_of_frame.state import Coordinates, MapObject, Source
from out_of_frame.web_search import TavilyWebSearch

# Tavily's results for one query change from one call to the next, so a search counts as
# finding a page if any of these tries finds it.
SEARCH_TRIES = 3

# A map label's tolerance is half the diagonal of its object's bounds, so that the centre of an
# element that a map edit makes out of the same object is still within it; at least this. A
# plan's ID comes from its planid, which no map edit changes, so a plan gets only this: a wider
# one could match a new plan to the label of one that it pushed out of the nearest five.
MIN_TOLERANCE_M = 50


def record(address: str, name: str) -> str:
    """The labels to fill in, as YAML, after the address, the map and the plans are recorded
    under the name. An earlier recording is never overwritten."""
    paths = find_recordings(name)
    if taken := [str(path) for path in paths if path.exists()]:
        sys.exit(f"already recorded: {', '.join(taken)}")
    found, geocoded = geocoding.geocode(address, "nominatim-1", berlin_only=True)
    if found.coordinates is None:
        sys.exit(f"{address}: {geocoding.explain(found, geocoded, berlin_only=True)}")
    on_map, map_source = map_objects.fetch_map_objects(found.coordinates)
    planned, plans_source = plans.fetch_plans(found.coordinates)
    addresses = map_objects.fetch_addresses(on_map, [map_source])
    tolerances = measure_map_tolerances(on_map, map_source)
    tolerances |= {plan.id: MIN_TOLERANCE_M for plan in planned}
    on_map = [o.model_copy(update={"addresses": addresses.get(o.id, [])}) for o in on_map]
    for path, source in zip(paths, [geocoded, map_source, plans_source], strict=True):
        with path.open("x", encoding="utf-8") as f:
            f.write(source.content)
    lines = [f"property: {format_coordinates(found.coordinates)}", "labels:"]
    for map_object in on_map + planned:
        lines += format_label(map_object, tolerances[map_object.id])
    return "\n".join(lines) + "\n"


def measure_map_tolerances(objects: list[MapObject], source: Source) -> dict[str, int]:
    elements = map_objects.find_elements(objects, [source])
    tolerances = {}
    for map_object, element in zip(objects, elements, strict=True):
        bounds = element.get("bounds")
        corners = (
            [(bounds["minlat"], bounds["minlon"]), (bounds["maxlat"], bounds["maxlon"])]
            if bounds
            else []
        )
        tolerances[map_object.id] = measure_tolerance(map_object.coordinates, corners)
    return tolerances


def measure_tolerance(centre: Coordinates, corners: list[tuple[float, float]]) -> int:
    """Half the diagonal of the bounds, rounded up to ten metres, and at least the minimum."""
    if not corners:
        return MIN_TOLERANCE_M
    (x1, y1), (x2, y2) = (map_objects.project(centre, corner) for corner in corners)
    half = math.hypot(x2 - x1, y2 - y1) / 2
    return max(MIN_TOLERANCE_M, math.ceil(half / 10) * 10)


def format_label(map_object: MapObject, tolerance_m: int) -> list[str]:
    """A label to fill in, with what the agent sees of the object as comments."""
    seen = " | ".join(map_object.map_text().splitlines())
    return [
        f"  # {map_object.distance_from_property_m:.0f} m: {seen}",
        "  - id: TODO",
        f"    object_id: {map_object.id}",
        f"    category: {map_object.details['category']}",
        f"    coordinates: {format_coordinates(map_object.coordinates)}",
        f"    distance_tolerance_m: {tolerance_m}",
        "    identified_type: TODO",
        "    status: TODO",
        "    source_url: TODO",
        "    search: TODO",
    ]


def format_coordinates(coordinates: Coordinates) -> str:
    return f"{{lat: {coordinates.lat}, lon: {coordinates.lon}}}"


def check(path: Path) -> bool:
    """Whether each scored label's search finds its page among the results that the agent
    would get, and the page of each label without a search is linked in its object's recorded
    data. Prints each label that fails."""
    expected = load(path).expected
    if not isinstance(expected, ExpectedRun):
        sys.exit(f"{path}: not an end-to-end task")
    data = read_object_data(expected.recorded_as, expected.property)
    web_search, passed = TavilyWebSearch(), True
    for label in expected.labels:
        if label.left_out is not None:
            continue
        if label.search is None:
            if label.source_url not in data.get(label.object_id, []):
                passed = False
                print(f"{label.id}: no search, and its object's data do not link its page")
            continue
        tries = []
        for _ in range(SEARCH_TRIES):
            tries.append([page.url for page in web_search.search(label.search)])
            if finds(label, tries[-1]):
                break
        else:
            passed = False
            print(f"{label.id}: {label.search!r} does not find {label.source_url}; it finds:")
            print("\n".join(f"  {url}" for url in dict.fromkeys(sum(tries, []))))
    return passed


def read_object_data(name: str, origin: Coordinates) -> dict[str, list[str]]:
    """The values of each recorded object's own fields, by the ID the agent's code gives it: an
    OSM element's tags and a plan's WFS fields."""
    _, overpass, bplan = find_recordings(name)
    data = {
        map_objects.build_id(element): list(element.get("tags", {}).values())
        for element in json.loads(overpass.read_text(encoding="utf-8"))["elements"]
        if element["type"] != "count"
    }
    for response in json.loads(bplan.read_text(encoding="utf-8")).values():
        for feature in response["features"]:
            if feature.get("geometry") is not None:
                # Only the ID is used, so the category and source ID can be any.
                id = plans.build_plan(feature, "planned", origin, "bplan").id
                data.setdefault(id, []).extend(map(str, feature["properties"].values()))
    return data


def finds(label: AddressLabel, urls: list[str]) -> bool:
    return normalise(label.source_url or "") in map(normalise, urls)


def normalise(url: str) -> str:
    return url.removesuffix("/")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address", nargs="?", help="the property, as the user would write it")
    parser.add_argument("name", nargs="?", help="the fixtures' name, such as e1-freiheit-22")
    parser.add_argument("--check", type=Path, help="an end-to-end task whose searches to check")
    args = parser.parse_args()
    if args.check:
        sys.exit(0 if check(args.check) else 1)
    if not (args.address and args.name):
        parser.error("give an address and a name, or --check with a task")
    print(record(args.address, args.name), end="")


if __name__ == "__main__":
    main()
