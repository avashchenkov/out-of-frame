# /// script
# requires-python = ">=3.14"
# dependencies = ["pyyaml"]
# ///
"""Spike (roadmap step 3): how many objects of each category does Overpass return near a
few addresses, and how many have no name?

Exploratory code, outside the checks, never extended. Run: uv run spikes/overpass-counts/spike.py
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ADDRESSES = [
    "Freiheit 22, 13597 Berlin",  # near Klärwerk Ruhleben
    "Richard-Byrd-Straße 39, 14089 Berlin",  # near the former Gatow airfield
    "Corinthstraße 60, 10245 Berlin",  # near the planned A100, 17th section
    "Saganer Straße 8, 10317 Berlin",  # near the Klingenberg power station
]
RESEARCH_SCOPE = Path(__file__).parents[2] / "src/out_of_frame/data/research_scope.yaml"
HEADERS = {"User-Agent": "out-of-frame-spike (github.com/avashchenkov/out-of-frame)"}


def get_json(url, data=None):
    for attempt in range(5):
        try:
            request = urllib.request.Request(url, data, HEADERS)
            with urllib.request.urlopen(request, timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 504) or attempt == 4:
                raise
            time.sleep(60)  # the public Overpass instance is often busy


def geocode(address):
    query = urllib.parse.urlencode({"q": address, "format": "jsonv2", "limit": 1})
    place = get_json(f"https://nominatim.openstreetmap.org/search?{query}")[0]
    time.sleep(1)  # Nominatim allows one request per second
    return float(place["lat"]), float(place["lon"])


def tag_filter(tags):
    # {k: v, k2: [a, b]} -> ["k"="v"]["k2"~"^(a|b)$"]
    return "".join(
        f'["{k}"~"^({"|".join(v)})$"]' if isinstance(v, list) else f'["{k}"="{v}"]'
        for k, v in tags.items()
    )


def overpass(classes, lat, lon):
    # One query for all classes, as in the architecture. Each class's output starts with its count.
    query = "[out:json][timeout:90];"
    for cls in classes:
        around = f"nwr(around:{cls['radius_m']},{lat},{lon})"
        union = "".join(f"{around}{tag_filter(tags)};" for tags in cls["osm_tags"])
        query += f"({union});out count;out tags;"
    data = urllib.parse.urlencode({"data": query}).encode()
    response = get_json("https://overpass-api.de/api/interpreter", data)
    if "remark" in response:  # a timeout or other error; the output may be cut off
        raise RuntimeError(response["remark"])
    groups = []
    for e in response["elements"]:
        if e["type"] == "count":
            groups.append([])
        else:
            groups[-1].append(e)
    return groups


classes = [c for c in yaml.safe_load(RESEARCH_SCOPE.read_text())["categories"] if c["source"] == "overpass"]
for address in ADDRESSES:
    lat, lon = geocode(address)
    print(f"\n{address} ({lat:.5f}, {lon:.5f})")
    print("  class       elements  no name  no name or ref  distinct names or refs")
    for cls, elements in zip(classes, overpass(classes, lat, lon), strict=True):
        tags = [e["tags"] for e in elements]
        # Roads and railways carry a ref (A 100, 6020) instead of a name, on every segment.
        ids = [t.get("name") or t.get("ref") for t in tags]
        unnamed, labels = sum("name" not in t for t in tags), len(set(ids) - {None})
        print(f"  {cls['id']:<10} {len(tags):>9} {unnamed:>8} {ids.count(None):>15} {labels:>23}")
