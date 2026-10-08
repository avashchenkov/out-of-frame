"""The research scope, read from data/research_scope.yaml: what the agent fetches around a
property, and what a finding can say about an object.

The categories say what to fetch from each source and how far, such as industrial sites from
OpenStreetMap or planned objects from B-Plans. A map object has no category field: code puts
the category into its details, next to the fields of its source. A finding classifies the
object with one of the identified types and one of the finding statuses.
"""

from functools import cache
from importlib.resources import files
from typing import Literal

import yaml

from out_of_frame.record import Record


class MapObjectCategory(Record):
    """What to fetch from one source, and how far, such as industrial sites from the map."""

    id: str  # such as "industry"; code puts it into the details of each object it fetches
    name: str  # for people, such as "Industrial and energy sites"
    radius_m: int  # how far from the property to fetch, to the nearest edge of an object
    source: Literal["overpass", "bplan_wfs"]  # the API that code fetches from
    # Overpass only: an object matches if it has all the tags of one entry.
    osm_tags: list[dict[str, str | list[str]]] = []
    # B-Plan WFS only: the plan layers to fetch
    wfs_feature_types: list[str] = []


class ResearchScope(Record):
    # The values that a finding can give, each with its meaning. The finding prompt shows the
    # meanings to the model.
    finding_statuses: dict[str, str]  # for Finding.status, such as operating: In use now.
    identified_types: dict[str, str]  # for Finding.identified_type, such as plant
    categories: list[MapObjectCategory]  # what code fetches from the sources


@cache
def load() -> ResearchScope:
    """The research scope, read once."""
    path = files("out_of_frame").joinpath("data/research_scope.yaml")
    return ResearchScope.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
