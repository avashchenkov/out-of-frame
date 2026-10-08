"""The run state as a logical data model, see docs/architecture.md#the-state.

TODO: Message, Address, Destination, Journey and the run state itself, with the steps that
use them. A rejected finding and its reason in the investigation history come with the
grounding check in step 5.
"""

from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, model_validator

from out_of_frame.record import Record


class Coordinates(Record):
    lat: float
    lon: float


class Source(Record):
    """One API response, or one snippet or page from Tavily."""

    id: str
    kind: Literal["geocoding", "map", "plans", "web search"]
    request: str
    url: str
    content: str


class MapObject(Record):
    """An object on the map near the property, such as a plant, an airport or a motorway."""

    model_config = Record.model_config | ConfigDict(coerce_numbers_to_str=True)  # OSM tags

    id: str
    name: str | None
    details: dict[str, str]  # the category and the source's own fields, such as landuse=industrial
    addresses: list[str]
    coordinates: Coordinates  # for an area or a line, the centre of its bounds
    distance_from_property_m: float  # to the object's nearest edge
    source_id: str  # the ID of the Source: the map or plan response the object comes from

    def map_text(self) -> str:
        """The object's own data as text: its name, details and addresses. A key fact that a
        finding takes from the map must appear in it."""
        lines = [self.name or ""] + [f"{key}={value}" for key, value in self.details.items()]
        return "\n".join(lines + self.addresses)


class Finding(Record):
    """What an investigation found about one map object."""

    # The descriptions are also the model's instructions for each field: see finding.py.
    map_object_id: str  # the ID of the MapObject; set by code, never by the model
    outcome: Literal["identified", "unidentified"] = Field(
        description="identified if a source settles what the object is"
    )
    identified_type: str | None = Field(
        description="One of the listed types; other if the sources settle what the object is "
        "and no listed type fits; null if they do not settle it."
    )
    status: str | None = Field(
        description="One of the listed statuses; null if the sources do not settle it."
    )
    why_it_matters: str = Field(
        description="One sentence on what the object means for someone living at the "
        "property. Empty if the object is unidentified."
    )
    key_facts: list[str] = Field(
        description="Short quotes, copied word for word from a cited source or the map data."
    )
    evidence_ids: list[str] = Field(
        description="The IDs of the sources that the key facts come from, such as web-1 or "
        "the map's source ID, without brackets."
    )


class ToolCall(Record):
    role: Literal["model"]
    tool: Literal["search", "extract"]
    query: str | None = None
    url: str | None = None

    @model_validator(mode="after")
    def check_argument(self) -> Self:
        wanted = "query" if self.tool == "search" else "url"
        given = [name for name in ("query", "url") if getattr(self, name) is not None]
        if given != [wanted]:
            raise ValueError(f"a {self.tool} call takes only a {wanted}")
        return self


class ToolResult(Record):
    """The pages a tool call showed, by ID; their text is in the state's pages."""

    role: Literal["tool"]
    pages: list[str]


HistoryEntry = Annotated[ToolCall | ToolResult, Field(discriminator="role")]


class InvestigationState(Record):
    """The state of one investigation subgraph run.

    TODO: in step 5, each model call sees the history with the text of the pages it shows.
    """

    map_object: MapObject
    history: list[HistoryEntry]
    pages: list[Source]
    finding: Finding | None
