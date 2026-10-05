"""Load eval tasks and check their format, see docs/eval-architecture.md#files.

The loader splits a task into what the agent gets and what only the graders read.
"""

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NoReturn, Self

import yaml
from pydantic import Field, ValidationError, model_validator

from evals.graders.finding import Expected
from out_of_frame import checklist
from out_of_frame.checklist import UNKNOWN
from out_of_frame.state import InvestigationState, NearbyObject, Record, ToolCall

EVALS = Path(__file__).parent
TASKS = EVALS / "tasks"
STATES = EVALS / "states"
FIXTURES = EVALS / "fixtures"

type Inputs = NearbyObject | InvestigationState


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
    location: tuple[float, float]
    distance_tolerance_m: float
    class_: str = Field(alias="class")
    type: str
    status: str
    source_url: str  # the address of one page that shows why the label is true


class TaskExpected(Record):
    """Either the label of a real object, or the result that follows a written state."""

    label: Label | None = None
    outcome: Literal["identified", "unidentified"] | None = None
    type: str | None = None
    status: str | None = None

    @model_validator(mode="after")
    def check_one_kind(self) -> Self:
        written = [self.outcome, self.type, self.status]
        if self.label is not None and written != [None, None, None]:
            raise ValueError("give a label, or outcome, type and status, not both")
        if self.label is None and None in written:
            raise ValueError("without a label, give outcome, type and status")
        return self

    def result(self) -> Expected:
        if self.label:
            outcome = "unidentified" if self.label.type == UNKNOWN else "identified"
            return Expected(outcome, self.label.type, self.label.status)
        return Expected(self.outcome, self.type, self.status)


class TaskInput(Record):
    object: NearbyObject | None = None
    sources: list[RecordedSource] = []
    state: str | None = None


class TaskFile(Record):
    id: str
    suite: Literal["finding", "live investigation"]
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
    expected: Expected


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

    match task.suite, task.input.object, state:
        case "live investigation", NearbyObject() as obj, None:
            if obj.source_id not in [source.id for source in task.input.sources]:
                fail("the object's source is not among the task's sources")
            inputs = obj
        case "finding", None, InvestigationState():
            obj = state.object
            check_state(state, fail)
            inputs = state
        case _:
            fail("a live investigation task gives an object, a finding task gives a state")

    expected = task.expected.result()
    if obj.class_ not in checklist.class_ids():
        fail(f"unknown class {obj.class_!r}")
    if task.expected.label and task.expected.label.class_ != obj.class_:
        fail("the label's class differs from the object's")
    if expected.type not in checklist.types(obj.class_) + [UNKNOWN]:
        fail(f"type {expected.type!r} is not in the list of class {obj.class_!r}")
    if expected.status not in checklist.statuses() + [UNKNOWN]:
        fail(f"unknown status {expected.status!r}")
    if (expected.outcome == "unidentified") != (expected.type == UNKNOWN):
        fail("an object is unidentified exactly when its type is unknown")
    if task.date == "today" and task.suite != "live investigation":
        fail("only a live task runs with the date of the trial")
    return Task(task.id, task.suite, None if task.date == "today" else task.date, inputs, expected)


def check_state(state: InvestigationState, fail) -> None:
    roles = [entry.role for entry in state.history]
    if roles != ["model", "tool"] * (len(roles) // 2):
        fail("the history must alternate a tool call and its result, starting with a call")
    calls = [entry for entry in state.history if isinstance(entry, ToolCall)]
    if len(calls) > checklist.tool_cap():
        fail(f"{len(calls)} tool calls, above the cap of {checklist.tool_cap()}")
    ids = [page.id for page in state.pages] + [state.object.source_id]
    shown = [id for entry in state.history if not isinstance(entry, ToolCall) for id in entry.pages]
    if len(set(ids)) != len(ids):
        fail("two sources have the same ID, counting the object's map source")
    if set(shown) != set(ids[:-1]):
        fail("every page must be shown in the history, and only pages")


def read_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))
