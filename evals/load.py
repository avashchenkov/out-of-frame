"""Load eval tasks and check their format, see docs/eval-architecture.md#files.

The loader splits a task into what the agent gets and what only the graders read.
"""

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NoReturn, Self

import yaml
from pydantic import ValidationError, model_validator

from evals.graders.finding import Expected
from out_of_frame import research_scope
from out_of_frame.config import TOOL_CAP
from out_of_frame.record import Record
from out_of_frame.state import Coordinates, InvestigationState, MapObject, RunState, ToolCall
from out_of_frame.web_search import PageText

EVALS = Path(__file__).parent
TASKS = EVALS / "tasks"
STATES = EVALS / "states"
FIXTURES = EVALS / "fixtures"

type Inputs = MapObject | InvestigationState | RunState | PageText | Conversation


class TaskFormatError(Exception):
    pass


class RecordedSource(Record):
    """A source response kept as a fixture, for replay."""

    id: str
    kind: Literal["geocoding", "map", "plans", "web search"]
    url: str
    request: str
    fixture: str


class Conversation(Record):
    """What an input loop task gives the agent: the user's messages, the first one and a reply
    to each expected question, and the recorded Nominatim responses it geocodes from."""

    messages: list[str]
    sources: list[RecordedSource]


class Label(Record):
    """The true type and status of a real object.

    See docs/eval-architecture.md#ground-truth-labels.
    """

    id: str
    coordinates: Coordinates
    distance_tolerance_m: float
    identified_type: str | None  # None: the object cannot be identified
    status: str | None  # None: no source settles it
    source_url: str  # the address of one page that shows why the label is true


class TaskExpected(Record):
    """The label of a real object, the result that follows a written state, whether the
    injection check should flag a page, or where the input loop should find the property."""

    label: Label | None = None
    outcome: Literal["identified", "unidentified"] | None = None
    identified_type: str | None = None
    status: str | None = None
    flagged: bool | None = None
    property: Coordinates | None = None  # TODO: the destinations, with I1 and I3 (step 9)

    @model_validator(mode="after")
    def check_one_kind(self) -> Self:
        written = {
            "outcome",
            "identified_type",
            "status",
        } & self.model_fields_set  # null counts as given
        kinds = [self.label is not None, bool(written), self.flagged is not None]
        if sum(kinds) + (self.property is not None) != 1:
            raise ValueError(
                "give a label, or outcome, identified_type and status, or flagged, or property"
            )
        if written and len(written) < 3:
            raise ValueError("give outcome, identified_type and status together")
        return self

    def result(self) -> Expected | bool | Coordinates:
        if self.property is not None:
            return self.property
        if self.flagged is not None:
            return self.flagged
        if self.label:
            outcome = "unidentified" if self.label.identified_type is None else "identified"
            return Expected(outcome, self.label.identified_type, self.label.status)
        return Expected(self.outcome, self.identified_type, self.status)


class TaskInput(Record):
    messages: list[str] = []  # the user's messages in an input loop task
    map_object: MapObject | None = None
    sources: list[RecordedSource] = []
    state: str | None = None
    page: PageText | None = None  # a snippet or page for the injection check


class TaskFile(Record):
    id: str
    suite: Literal[
        "finding", "live investigation", "injection check", "triage", "report", "input loop"
    ]
    covers: str
    date: dt.date | Literal["today"]
    input: TaskInput
    expected: TaskExpected | None = None  # a report task's graders need only its state


@dataclass(frozen=True)
class Task:
    id: str
    suite: str
    date: dt.date | None  # None: the date of the trial
    inputs: Inputs
    # bool: whether the injection check should flag the page; Coordinates: where the input loop
    # should find the property; None for a report task, whose graders read only its state
    expected: Expected | bool | Coordinates | None


def load_all() -> list[Task]:
    return [load(path) for path in sorted(TASKS.glob("*.yaml"))]


def load(path: Path) -> Task:
    def fail(message: str) -> NoReturn:
        raise TaskFormatError(f"{path.name}: {message}")

    try:
        task = TaskFile.model_validate(read_yaml(path))
        state_model = RunState if task.suite == "report" else InvestigationState
        state = (
            state_model.model_validate(read_yaml(STATES / task.input.state))
            if task.input.state
            else None
        )
        for source in task.input.sources:
            (FIXTURES / source.fixture).stat()
    except (ValidationError, OSError, yaml.YAMLError) as e:
        fail(str(e))

    if bool(task.input.messages) != (task.suite == "input loop"):
        fail("an input loop task, and only it, gives the user's messages")
    match task.suite, task.input.map_object, state, task.input.page:
        case "live investigation", MapObject() as map_object, None, None:
            match [s.kind for s in task.input.sources if s.id == map_object.source_id]:
                case ["map" | "plans" as kind]:
                    inputs = InvestigationState.start(map_object, kind)
                case _:
                    fail("the map object's source must be one map or plans source of the task")
        case "triage", MapObject() as map_object, None, None:
            inputs = map_object
        case "finding", None, InvestigationState(), None:
            check_state(state, fail)
            inputs = state
        case "report", None, RunState(), None:
            check_run_state(state, fail)
            inputs = state
        case "injection check", None, None, PageText() as page:
            inputs = page
        case "input loop", None, None, None:
            if any(source.kind != "geocoding" for source in task.input.sources):
                fail("an input loop task replays only geocoding responses")
            inputs = Conversation(messages=task.input.messages, sources=task.input.sources)
        case _:
            fail(
                "a live investigation or triage task gives a map object, a finding or report "
                "task a state, an injection check task a page, an input loop task messages"
            )

    if (task.expected is None) != (task.suite == "report"):
        fail("a report task, and only it, has no expected result")
    expected = task.expected.result() if task.expected else None
    if isinstance(expected, bool) != (task.suite == "injection check"):
        fail("an injection check task, and only it, expects flagged")
    if isinstance(expected, Coordinates) != (task.suite == "input loop"):
        fail("an input loop task, and only it, expects the property")
    if isinstance(expected, Expected):
        check_expected(expected, fail)
    if task.date == "today" and task.suite != "live investigation":
        fail("only a live task runs with the date of the trial")
    return Task(task.id, task.suite, None if task.date == "today" else task.date, inputs, expected)


def check_expected(expected: Expected, fail) -> None:
    scope = research_scope.load()
    if expected.identified_type not in [*scope.identified_types, None]:
        fail(f"unknown identified type {expected.identified_type!r}")
    if expected.status is not None and expected.status not in scope.finding_statuses:
        fail(f"unknown status {expected.status!r}")
    if (expected.outcome == "unidentified") != (expected.identified_type is None):
        fail("an object is unidentified exactly when it has no type")


def check_run_state(state: RunState, fail) -> None:
    """A written run state refers only to its own objects and sources, so that a typo cannot
    quietly turn an object into one that was not investigated."""
    objects = {map_object.id for map_object in state.map_objects}
    sources = {source.id for source in state.sources}
    for map_object in state.map_objects:
        if map_object.source_id not in sources:
            fail(f"{map_object.id}: unknown source {map_object.source_id!r}")
    for finding in state.findings:
        if finding.map_object_id not in objects:
            fail(f"a finding of an unknown object {finding.map_object_id!r}")
        if finding.evidence_id is not None and finding.evidence_id not in sources:
            fail(f"{finding.map_object_id}: unknown evidence {finding.evidence_id!r}")


def check_state(state: InvestigationState, fail) -> None:
    roles = [entry.role for entry in state.history]
    if roles != ["model", "tool"] * (len(roles) // 2):
        fail("the history must alternate a tool call and its result, starting with a call")
    calls = [entry for entry in state.history if isinstance(entry, ToolCall)]
    if len(calls) > TOOL_CAP:
        fail(f"{len(calls)} tool calls, above the cap of {TOOL_CAP}")
    ids = [page.id for page in state.pages] + [state.map_object.source_id]
    shown = [id for entry in state.history if not isinstance(entry, ToolCall) for id in entry.pages]
    if len(set(ids)) != len(ids):
        fail("two sources have the same ID, counting the object's map source")
    if set(shown) != set(ids[:-1]):
        fail("every page must be shown in the history, and only pages")


def read_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))
