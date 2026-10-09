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
from out_of_frame.state import Coordinates, InvestigationState, MapObject, ToolCall
from out_of_frame.web_search import PageText

EVALS = Path(__file__).parent
TASKS = EVALS / "tasks"
STATES = EVALS / "states"
FIXTURES = EVALS / "fixtures"

type Inputs = MapObject | InvestigationState | PageText


class TaskFormatError(Exception):
    pass


class RecordedSource(Record):
    """A source response kept as a fixture, for replay."""

    id: str
    kind: Literal["geocoding", "map", "plans", "web search"]
    url: str
    request: str
    fixture: str


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
    """The label of a real object, the result that follows a written state, or whether the
    injection check should flag a page."""

    label: Label | None = None
    outcome: Literal["identified", "unidentified"] | None = None
    identified_type: str | None = None
    status: str | None = None
    flagged: bool | None = None

    @model_validator(mode="after")
    def check_one_kind(self) -> Self:
        written = {
            "outcome",
            "identified_type",
            "status",
        } & self.model_fields_set  # null counts as given
        if (self.label is not None) + bool(written) + (self.flagged is not None) != 1:
            raise ValueError("give a label, or outcome, identified_type and status, or flagged")
        if written and len(written) < 3:
            raise ValueError("give outcome, identified_type and status together")
        return self

    def result(self) -> Expected | bool:
        if self.flagged is not None:
            return self.flagged
        if self.label:
            outcome = "unidentified" if self.label.identified_type is None else "identified"
            return Expected(outcome, self.label.identified_type, self.label.status)
        return Expected(self.outcome, self.identified_type, self.status)


class TaskInput(Record):
    map_object: MapObject | None = None
    sources: list[RecordedSource] = []
    state: str | None = None
    page: PageText | None = None  # a snippet or page for the injection check


class TaskFile(Record):
    id: str
    suite: Literal["finding", "live investigation", "injection check"]
    covers: str
    date: dt.date | Literal["today"]
    input: TaskInput
    expected: TaskExpected


@dataclass(frozen=True)
class Task:
    id: str
    suite: str
    date: dt.date | None  # None: the date of the trial
    inputs: Inputs
    expected: Expected | bool  # bool: whether the injection check should flag the page


def load_all() -> list[Task]:
    return [load(path) for path in sorted(TASKS.glob("*.yaml"))]


def load(path: Path) -> Task:
    def fail(message: str) -> NoReturn:
        raise TaskFormatError(f"{path.name}: {message}")

    try:
        task = TaskFile.model_validate(read_yaml(path))
        state = (
            InvestigationState.model_validate(read_yaml(STATES / task.input.state))
            if task.input.state
            else None
        )
        for source in task.input.sources:
            (FIXTURES / source.fixture).stat()
    except (ValidationError, OSError, yaml.YAMLError) as e:
        fail(str(e))

    match task.suite, task.input.map_object, state, task.input.page:
        case "live investigation", MapObject() as map_object, None, None:
            if map_object.source_id not in [source.id for source in task.input.sources]:
                fail("the map object's source is not among the task's sources")
            inputs = map_object
        case "finding", None, InvestigationState(), None:
            check_state(state, fail)
            inputs = state
        case "injection check", None, None, PageText() as page:
            inputs = page
        case _:
            fail(
                "a live investigation task gives a map object, a finding task a state, an "
                "injection check task a page"
            )

    expected = task.expected.result()
    if isinstance(expected, bool) != (task.suite == "injection check"):
        fail("an injection check task, and only it, expects flagged")
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
