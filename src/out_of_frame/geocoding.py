"""Geocoding with Nominatim: the coordinates of an address, see docs/sources.md#nominatim.

TODO: in step 9, a destination may be outside Berlin.
"""

import json
import re
import time

import httpx

from out_of_frame.config import NOMINATIM_URL, SOURCE_ATTEMPTS, USER_AGENT
from out_of_frame.state import Address, Coordinates, Source

# The city's name as a word of its own, not as part of a street name such as Berliner Straße.
BERLIN = re.compile(r"\bBerlin\b", re.IGNORECASE)


class GeocodingError(Exception):
    """Nominatim failed after its retries. Nothing can be checked without the address, so the
    run stops."""


def geocode(text: str, source_id: str) -> tuple[Address, Source]:
    """The address with its coordinates if Nominatim finds exactly one building with it in
    Berlin, and Nominatim's response, which says why when it does not. A match of a street or
    a district alone has no house number, so it does not count: its coordinates would not be
    the property's. Code adds the city to an address that does not name it: Nominatim searches
    the whole world, and returns only its first ten matches."""
    query = text if BERLIN.search(text) else f"{text}, Berlin"
    results = call_nominatim(query)
    source = Source(
        id=source_id,
        kind="geocoding",
        request=query,
        url=NOMINATIM_URL,
        content=json.dumps(results, ensure_ascii=False),
    )
    address = Address(text=text, source_id=source_id)
    in_berlin = [building for building in find_buildings(results) if is_in_berlin(building)]
    if len(in_berlin) == 1:
        [building] = in_berlin
        coordinates = Coordinates(lat=float(building["lat"]), lon=float(building["lon"]))
        address = address.model_copy(update={"coordinates": coordinates})
    return address, source


def explain(address: Address, source: Source) -> str | None:
    """Why the address has no coordinates, for the question to the user, or None if it has."""
    if address.coordinates is not None:
        return None
    results = json.loads(source.content)
    buildings = find_buildings(results)
    in_berlin = [building for building in buildings if is_in_berlin(building)]
    if in_berlin:
        matches = "; ".join(name_building(building) for building in in_berlin)
        return f"Several buildings in Berlin match {address.text!r}: {matches}."
    if buildings:
        return f"{address.text!r} is outside Berlin, and only Berlin is checked."
    if results:
        return f"{address.text!r} matches only a street or an area, not one building."
    return f"No place in Berlin matches {address.text!r}."


def find_buildings(results: list[dict]) -> list[dict]:
    """The matches with a house number, each building once: Nominatim can return a building
    twice, as an address point and as its outline. The region and the district keep apart
    buildings with the same street and number, even without a postcode."""
    buildings = {}
    for result in results:
        address = result["address"]
        if "house_number" in address:
            region = address.get("ISO3166-2-lvl4")
            key = region, find_district(address), address.get("road"), address["house_number"]
            buildings.setdefault((*key, address.get("postcode")), result)
    return list(buildings.values())


def find_district(address: dict) -> str | None:
    return address.get("suburb") or address.get("city_district") or address.get("borough")


def is_in_berlin(result: dict) -> bool:
    return result["address"].get("ISO3166-2-lvl4") == "DE-BE"


def name_building(result: dict) -> str:
    """A building's address that Nominatim finds again, and its district for the user, such as
    Hauptstraße 1, 10317 Berlin (Rummelsburg). Without a postcode, the district is part of the
    address, as it is what tells the building from the others."""
    address = result["address"]
    street = f"{address.get('road', '')} {address['house_number']}".strip()
    district = find_district(address)
    if "postcode" not in address:
        return ", ".join(part for part in [street, district, "Berlin"] if part)
    name = f"{street}, {address['postcode']} Berlin"
    return f"{name} ({district})" if district else name


def call_nominatim(text: str) -> list[dict]:
    """Nominatim's matches for the address, tried again on any failure."""
    for attempt in range(1, SOURCE_ATTEMPTS + 1):
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
