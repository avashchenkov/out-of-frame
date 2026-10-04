"""The run state as a logical data model, see docs/architecture.md#the-state.

TODO: Message, Address, Destination, Journey and the run state itself, with the steps that
use them. A rejected finding and its reason in the investigation history come with the
grounding check in step 5.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Record(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, populate_by_name=True, serialize_by_alias=True
    )


class Point(Record):
    lat: float
    lon: float


class Source(Record):
    """One API response, or one snippet or page from Tavily."""

    id: str
    kind: Literal["geocoding", "map", "plans", "web search"]
    request: str
    url: str
    content: str


class NearbyObject(Record):
    model_config = Record.model_config | ConfigDict(coerce_numbers_to_str=True)  # OSM tags

    id: str
    class_: str = Field(alias="class")
    name: str | None
    details: dict[str, str]
    addresses: list[str]
    point: Point
    distance_m: float
    source_id: str


class Finding(Record):
    object_id: str
    outcome: Literal["identified", "unidentified"]
    type: str
    status: str
    why_it_matters: str
    key_facts: list[str]
    evidence_ids: list[str]


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

    object: NearbyObject
    history: list[HistoryEntry]
    pages: list[Source]
    finding: Finding | None
