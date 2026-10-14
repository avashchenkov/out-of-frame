"""The run state as a logical data model, see docs/architecture.md#the-state.

TODO: Destination and Journey, and the run state's fields for them, with the steps that use
them (step 9).
"""

import operator
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, model_validator

from out_of_frame.record import Record


class Coordinates(Record):
    lat: float
    lon: float


class Message(Record):
    role: Literal["user", "agent"]
    text: str


class Address(Record):
    text: str  # as the extract call took it from the conversation; code never changes it
    coordinates: Coordinates | None = None  # only for exactly one precise match
    source_id: str | None = None  # the Nominatim response for this text, once it is geocoded


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
    evidence_id: str | None = Field(
        description="The ID of the one page that the finding rests on, without brackets, such "
        "as web-1; the rules say which page. The map's source ID only if no page adds a key "
        "fact that the finding needs. Null if the object is unidentified."
    )
    identified_type: str | None = Field(
        description="One of the listed types; other if the cited source and the map data "
        "settle what it is and no listed type fits; null if they do not settle it."
    )
    status: str | None = Field(
        description="One of the listed statuses, for today; null if the cited source and the "
        "map data do not settle it for today."
    )
    key_facts: list[str] = Field(
        description="One to three short quotes about this object, those that best settle what "
        "it is and whether it is in use. Each is copied word for word from the cited page or "
        "the map data, without added words or '...': only the words that show the fact, such as "
        "a name or an address, never a whole snippet or page, and never several lines joined "
        "into one. At least one if the object is identified, and at least one from the cited "
        "page, if it cites one."
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
            evidence_id=None,
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

    @property
    def args(self) -> dict[str, str]:
        """The call's arguments, as the model wrote them."""
        return {"query" if self.tool == "search" else "url": self.argument}


class ToolResult(Record):
    """The pages a tool call showed, by ID; their text is in the state's pages."""

    role: Literal["tool"]
    pages: list[str]


HistoryEntry = Annotated[ToolCall | ToolResult, Field(discriminator="role")]


# The kinds of Source that a map object comes from: the map, or the development plans.
type ObjectSourceKind = Literal["map", "plans"]


class InvestigationState(Record):
    """The state of one investigation subgraph run. LangGraph appends a node's history and pages
    to the lists, and replaces the other fields."""

    map_object: MapObject
    source_kind: ObjectSourceKind  # of the Source that map_object.source_id names
    history: Annotated[list[HistoryEntry], operator.add]
    pages: Annotated[list[Source], operator.add]
    finding: Finding | None
    web_search_failed: bool = False  # the finding is then unidentified; written states omit it

    @classmethod
    def start(cls, map_object: MapObject, source_kind: ObjectSourceKind) -> Self:
        """The state that an investigation starts from: its object and the kind of its source."""
        return cls(
            map_object=map_object, source_kind=source_kind, history=[], pages=[], finding=None
        )


type Service = Literal["map", "plans", "web search"]  # TODO: transit, with its step (step 9)


def add_new(old: list, new: list) -> list:
    """The old list with each new entry that it does not have yet."""
    return old + [entry for entry in new if entry not in old]


def replace_by_id(old: list, new: list) -> list:
    """The old list with each new entry in place of the old one with its ID, and the other new
    entries at the end, so that code can add to an object later, such as its addresses. An
    entry can be a record or, in a state that LangGraph has not validated yet, a dict."""

    def find_id(entry) -> str:
        return entry["id"] if isinstance(entry, dict) else entry.id

    new_by_id = {find_id(entry): entry for entry in new}
    return [new_by_id.pop(find_id(entry), entry) for entry in old] + list(new_by_id.values())


class RunState(Record):
    """The state of one run, see docs/architecture.md#the-state. LangGraph appends a node's
    messages, sources, map objects and findings to the lists, a map object in place of the one
    with its ID, adds each new failure, and replaces the property and the report."""

    messages: Annotated[list[Message], operator.add] = []  # the conversation in the input phase
    property: Address | None = None  # null until the user gives its address
    sources: Annotated[list[Source], operator.add] = []
    map_objects: Annotated[list[MapObject], replace_by_id] = []
    findings: Annotated[list[Finding], operator.add] = []
    failures: Annotated[list[Service], add_new] = []  # the services that failed after retries
    report: str | None = None  # the model's draft, then the report with its references filled in

    def find_source_kind(self, map_object: MapObject) -> ObjectSourceKind:
        """The kind of the source that the object comes from, by its source ID."""
        [kind] = [source.kind for source in self.sources if source.id == map_object.source_id]
        assert kind in ("map", "plans")  # what the map and the plans give
        return kind
