"""Geocoding with Nominatim: the coordinates of an address, see docs/sources.md#nominatim.

TODO: in step 7, an address that is not found, or that matches several places, leads to a
question for the user, and a destination may be outside Berlin.
"""

import time

import httpx

from out_of_frame.config import NOMINATIM_URL, SOURCE_ATTEMPTS, USER_AGENT
from out_of_frame.state import Coordinates


class GeocodingError(Exception):
    """Nominatim failed after its retries. Nothing can be checked without the address, so the
    run stops."""


def geocode(text: str) -> Coordinates | None:
    """The coordinates of the address, if Nominatim finds exactly one building with it in
    Berlin. A match of a street or a district alone has no house number, so it does not
    count: its coordinates would not be the property's."""
    # By address: Nominatim can return a building twice, as an address point and as its outline.
    buildings = {}
    for result in call_nominatim(text):
        address = result["address"]
        if "house_number" in address and address.get("ISO3166-2-lvl4") == "DE-BE":  # Berlin
            key = address.get("road"), address["house_number"], address.get("postcode")
            buildings[key] = result
    if len(buildings) != 1:
        return None
    [building] = buildings.values()
    return Coordinates(lat=float(building["lat"]), lon=float(building["lon"]))


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
