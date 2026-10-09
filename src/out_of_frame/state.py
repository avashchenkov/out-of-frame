"""The run state as a logical data model, see docs/architecture.md#the-state.

TODO: Message, Address, Destination, Journey and the run state itself, with the steps that
use them.
"""

import operator
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
        """The object's own data as text: its name, details and addresses. The category is left
        out: it is the agent's own fetch class, not data from the map. A key fact that a
        finding takes from the map must appear in this text."""
        details = [f"{key}={value}" for key, value in self.details.items() if key != "category"]
        lines = [self.name or ""] + details
        return "\n".join(lines + self.addresses)


class Finding(Record):
    """What an investigation found about one map object."""

    # The descriptions are also the model's instructions for each field: see finding.py.
    map_object_id: str  # the ID of the MapObject; set by code, never by the model
    outcome: Literal["identified", "unidentified"] = Field(
        description="identified if a source about this object settles what it is; the rules "
        "say which sources are about it"
    )
    identified_type: str | None = Field(
        description="One of the listed types; other if the sources about this object settle "
        "what it is and no listed type fits; null if they do not settle it."
    )
    status: str | None = Field(
        description="One of the listed statuses, for today; null if the sources do not settle "
        "it for today."
    )
    key_facts: list[str] = Field(
        description="Short quotes about this object, each copied word for word from one cited "
        "source or the map data, without added words or '...': only the words that show the "
        "fact, such as a name or an address, never a whole snippet or page. At least one if "
        "the object is identified."
    )
    evidence_ids: list[str] = Field(
        description="The IDs of the sources that the key facts come from, such as web-1, or "
        "the map's source ID for a quote from the map data, without brackets. At least one if "
        "the object is identified."
    )

    @classmethod
    def unidentified(cls, map_object_id: str) -> Self:
        """A finding that says nothing about the object: no type, no status, no evidence."""
        return cls(
            map_object_id=map_object_id,
            outcome="unidentified",
            identified_type=None,
            status=None,
            key_facts=[],
            evidence_ids=[],
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

    @property
    def argument(self) -> str:
        """The query of a search or the URL of a page read."""
        argument = self.query if self.tool == "search" else self.url
        assert argument is not None  # check_argument makes sure that it is set
        return argument


class ToolResult(Record):
    """The pages a tool call showed, by ID; their text is in the state's pages."""

    role: Literal["tool"]
    pages: list[str]


HistoryEntry = Annotated[ToolCall | ToolResult, Field(discriminator="role")]


class InvestigationState(Record):
    """The state of one investigation subgraph run. LangGraph appends a node's history and pages
    to the lists, and replaces the other fields."""

    map_object: MapObject
    history: Annotated[list[HistoryEntry], operator.add]
    pages: Annotated[list[Source], operator.add]
    finding: Finding | None
    web_search_failed: bool = False  # the finding is then unidentified; written states omit it
