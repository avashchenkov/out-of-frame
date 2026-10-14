"""Geocoding with Nominatim: the coordinates of an address, see docs/sources.md#nominatim."""

import json
import re
import time

import httpx

from out_of_frame.config import NOMINATIM_URL, SOURCE_ATTEMPTS, USER_AGENT
from out_of_frame.state import Address, Coordinates, Source

# The city's name as a word of its own, not as part of a street name such as Berliner Straße.
BERLIN = re.compile(r"\bBerlin\b", re.IGNORECASE)
# A German postcode: five digits as a word of their own.
POSTCODE = re.compile(r"\b\d{5}\b")

# Nominatim's usage policy allows at most one request a second.
NOMINATIM_INTERVAL_S = 1.0
last_request_at = float("-inf")  # time.monotonic() when the last request to Nominatim was sent


class GeocodingError(Exception):
    """Nominatim failed after its retries. Nothing can be checked without the address, so the
    run stops."""


def geocode(text: str, source_id: str, *, berlin_only: bool) -> tuple[Address, Source]:
    """The address with its coordinates if Nominatim finds exactly one building with it, and
    Nominatim's response, which says why when it does not. A match of a street or a district
    alone has no house number, so it does not count: its coordinates would not be the
    address's. Nor does a building with another postcode than the address names. The property
    must be in Berlin, so code adds the city to its address if it does not name it: Nominatim
    searches the whole world, and returns only its first ten matches. A destination may be
    anywhere."""
    query = text if not berlin_only or BERLIN.search(text) else f"{text}, Berlin"
    results = call_nominatim(query)
    source = Source(
        id=source_id,
        kind="geocoding",
        request=query,
        url=NOMINATIM_URL,
        content=json.dumps(results, ensure_ascii=False),
    )
    address = Address(text=text, source_id=source_id)
    candidates = match_postcode(text, find_buildings_in_area(results, berlin_only))
    if len(candidates) == 1:
        [building] = candidates
        coordinates = Coordinates(lat=float(building["lat"]), lon=float(building["lon"]))
        address = address.model_copy(update={"coordinates": coordinates})
    return address, source


def explain(address: Address, source: Source, *, berlin_only: bool) -> str | None:
    """Why the address has no coordinates, for the question to the user, or None if it has.
    berlin_only must be as when the address was geocoded."""
    if address.coordinates is not None:
        return None
    results = json.loads(source.content)
    in_area = find_buildings_in_area(results, berlin_only)
    candidates = match_postcode(address.text, in_area)
    where = " in Berlin" if berlin_only else ""
    if candidates:
        matches = "; ".join(name_building(building) for building in candidates)
        return f"Several buildings{where} match {address.text!r}: {matches}."
    if in_area:
        matches = "; ".join(name_building(building) for building in in_area)
        return f"{address.text!r} matches no building{where} with its postcode, only: {matches}."
    if find_buildings(results):  # buildings, but none in Berlin
        return f"{address.text!r} is outside Berlin, and only Berlin is checked."
    if results:
        return f"{address.text!r} matches only a street or an area, not one building."
    return f"No place{where} matches {address.text!r}."


def find_buildings_in_area(results: list[dict], berlin_only: bool) -> list[dict]:
    """The buildings that the address may be: in Berlin only, or anywhere."""
    buildings = find_buildings(results)
    if not berlin_only:
        return buildings
    return [building for building in buildings if is_in_berlin(building)]


def find_buildings(results: list[dict]) -> list[dict]:
    """The matches with a house number, each building once: Nominatim can return a building
    twice, as an address point and as its outline. Buildings with the same street and number
    are kept apart by their region, town and postcode, or without a postcode by their district,
    the parts of the address that the user is offered to tell them apart: several villages can
    share a postcode."""
    buildings = {}
    for result in results:
        address = result["address"]
        if "house_number" in address:
            place = address.get("postcode") or find_district(address)
            region, town = address.get("ISO3166-2-lvl4"), find_town(address)
            key = region, town, address.get("road"), address["house_number"], place
            buildings.setdefault(key, result)
    return list(buildings.values())


def match_postcode(text: str, buildings: list[dict]) -> list[dict]:
    """The buildings whose postcode does not differ from the one the text names, or all of
    them if it names none. Nominatim can return the same street and number in another
    district as its only match, and that building is another place."""
    named = POSTCODE.search(text)
    if named is None:
        return buildings
    postcode = named.group()
    return [
        building
        for building in buildings
        if building["address"].get("postcode", postcode) == postcode
    ]


def find_district(address: dict) -> str | None:
    return address.get("suburb") or address.get("city_district") or address.get("borough")


def find_town(address: dict) -> str | None:
    """The city, town or village, such as Berlin or Potsdam."""
    return address.get("city") or address.get("town") or address.get("village")


def is_in_berlin(result: dict) -> bool:
    return result["address"].get("ISO3166-2-lvl4") == "DE-BE"


def name_building(result: dict) -> str:
    """A building's address that Nominatim finds again, and its district for the user, such as
    Hauptstraße 1, 10317 Berlin (Rummelsburg). Without a postcode, the district is part of the
    address, as it is what tells the building from the others."""
    address = result["address"]
    street = f"{address.get('road', '')} {address['house_number']}".strip()
    district, town = find_district(address), find_town(address)
    if "postcode" not in address:
        return ", ".join(part for part in [street, district, town] if part)
    name = f"{street}, {' '.join(part for part in [address['postcode'], town] if part)}"
    return f"{name} ({district})" if district else name


def call_nominatim(text: str) -> list[dict]:
    """Nominatim's matches for the address, tried again on any failure. Each request, a retry
    too, waits until a second has passed since the last one."""
    global last_request_at
    for attempt in range(1, SOURCE_ATTEMPTS + 1):
        time.sleep(max(0.0, last_request_at + NOMINATIM_INTERVAL_S - time.monotonic()))
        last_request_at = time.monotonic()
        try:
            response = httpx.get(
                NOMINATIM_URL,
                params={"q": text, "format": "jsonv2", "addressdetails": 1},
                headers={"User-Agent": USER_AGENT},
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:  # also an answer cut off mid-JSON
            if attempt == SOURCE_ATTEMPTS:
                raise GeocodingError(f"{SOURCE_ATTEMPTS} tries failed: {error!r}") from error
            time.sleep(attempt)
    raise ValueError("OUT_OF_FRAME_SOURCE_ATTEMPTS must be at least 1")
