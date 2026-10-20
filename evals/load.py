"""Load eval tasks and check their format, see docs/eval-architecture.md#files.

The loader splits a task into what the agent gets and what only the graders read.
"""

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NoReturn, Self

import yaml
from pydantic import ValidationError, model_validator

from evals.graders.end_to_end import AddressLabel, ExpectedRun
from evals.graders.enough import ExpectedDecision
from evals.graders.finding import Expected
from evals.graders.input_loop import ExpectedDestination, ExpectedInput
from out_of_frame import research_scope
from out_of_frame.config import TOOL_CAP
from out_of_frame.record import Record
from out_of_frame.state import Coordinates, InvestigationState, MapObject, RunState, ToolCall
from out_of_frame.web_search import PageText

EVALS = Path(__file__).parent
TASKS = EVALS / "tasks"
STATES = EVALS / "states"
FIXTURES = EVALS / "fixtures"
# The responses that evals/label.py records at an end-to-end address, by their fixture folder.
RECORDINGS = ("nominatim", "overpass", "bplan")

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
    """What an input loop or end-to-end task gives the agent: the user's messages, the first one
    and a reply to each expected question, and the recorded Nominatim responses it geocodes
    from, none in an end-to-end task, which runs on live sources."""

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
    injection check should flag a page, the decision that follows a written search history, or
    how the input loop should end: the property and the places the user travels to; an
    end-to-end task adds the labels of the objects there."""

    label: Label | None = None
    outcome: Literal["identified", "unidentified"] | None = None
    identified_type: str | None = None
    status: str | None = None
    evidence_id: str | None = None  # the source a finding from a written state must cite
    flagged: bool | None = None
    stops: bool | None = None  # whether the model stops, or makes one more tool call
    reads: str | None = None  # the URL of a page that the model must read
    leaves_unread: str | None = None  # the URL of a page that the model must not read
    property: Coordinates | None = None
    destinations: list[ExpectedDestination] | None = None  # empty if the user travels nowhere
    labels: list[AddressLabel] | None = None
    recorded_as: str | None = None  # the fixtures' name, such as e4-teutonenstrasse-10

    @model_validator(mode="after")
    def check_one_kind(self) -> Self:
        written = {
            "outcome",
            "identified_type",
            "status",
        } & self.model_fields_set  # null counts as given
        decided = [self.stops is not None, self.reads is not None, self.leaves_unread is not None]
        kinds = [self.label is not None, bool(written), self.flagged is not None, any(decided)]
        if sum(kinds) + (self.property is not None) != 1 or sum(decided) > 1:
            raise ValueError(
                "give a label, or outcome, identified_type and status, or flagged, or one of "
                "stops, reads and leaves_unread, or property and destinations"
            )
        if written and len(written) < 3:
            raise ValueError("give outcome, identified_type and status together")
        if self.evidence_id is not None and not written:
            raise ValueError("give evidence_id only with outcome, identified_type and status")
        if (self.property is None) != (self.destinations is None):
            raise ValueError("give property and destinations together")
        if self.labels is not None and self.property is None:
            raise ValueError("give the labels with property and destinations")
        if (self.labels is None) != (self.recorded_as is None):
            raise ValueError("give the labels with the name they were recorded under")
        return self

    def result(self) -> Expected | bool | ExpectedDecision | ExpectedInput | ExpectedRun:
        if self.property is not None and self.destinations is not None and self.labels is not None:
            assert self.recorded_as is not None  # see check_one_kind
            return ExpectedRun(
                property=self.property,
                destinations=self.destinations,
                labels=self.labels,
                recorded_as=self.recorded_as,
            )
        if self.property is not None and self.destinations is not None:
            return ExpectedInput(property=self.property, destinations=self.destinations)
        if self.flagged is not None:
            return self.flagged
        if self.stops is not None or self.reads is not None or self.leaves_unread is not None:
            return ExpectedDecision(self.stops, self.reads, self.leaves_unread)
        if self.label:
            outcome = "unidentified" if self.label.identified_type is None else "identified"
            return Expected(outcome, self.label.identified_type, self.label.status)
        return Expected(self.outcome, self.identified_type, self.status, self.evidence_id)


class TaskInput(Record):
    messages: list[str] = []  # the user's messages in an input loop task
    map_object: MapObject | None = None
    sources: list[RecordedSource] = []
    state: str | None = None
    page: PageText | None = None  # a snippet or page for the injection check


class TaskFile(Record):
    id: str
    suite: Literal[
        "finding",
        "enough",
        "live investigation",
        "injection check",
        "triage",
        "report",
        "input loop",
        "end-to-end",
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
    # bool: whether the injection check should flag the page; ExpectedDecision: the decision
    # that follows a search history; ExpectedInput: how the input loop should end; ExpectedRun:
    # how an end-to-end run should end; None for a report task, whose graders read only its
    # state
    expected: Expected | bool | ExpectedDecision | ExpectedInput | ExpectedRun | None


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

    if bool(task.input.messages) != (task.suite in ("input loop", "end-to-end")):
        fail("an input loop or end-to-end task, and only it, gives the user's messages")
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
            sources = [page.id for page in state.pages] + [state.map_object.source_id]
            if task.expected and task.expected.evidence_id not in [None, *sources]:
                fail(f"unknown evidence_id {task.expected.evidence_id!r}")
            inputs = state
        case "enough", None, InvestigationState(), None:
            check_state(state, fail)
            check_decision_state(state, task.expected, fail)
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
        case "end-to-end", None, None, None:
            if len(task.input.messages) != 1 or task.input.sources:
                fail("an end-to-end task gives one first message and runs on live sources")
            inputs = Conversation(messages=task.input.messages, sources=[])
        case _:
            fail(
                "a live investigation or triage task gives a map object, a finding, Enough or "
                "report task a state, an injection check task a page, an input loop or "
                "end-to-end task messages"
            )

    if (task.expected is None) != (task.suite == "report"):
        fail("a report task, and only it, has no expected result")
    expected = task.expected.result() if task.expected else None
    if isinstance(expected, bool) != (task.suite == "injection check"):
        fail("an injection check task, and only it, expects flagged")
    if isinstance(expected, ExpectedDecision) != (task.suite == "enough"):
        fail("an Enough task, and only it, expects stops, reads or leaves_unread")
    if isinstance(expected, ExpectedRun) != (task.suite == "end-to-end"):
        fail("an end-to-end task, and only it, expects labels")
    if isinstance(expected, ExpectedInput) != (task.suite == "input loop"):
        fail("an input loop task, and only it, expects the property and the destinations alone")
    if isinstance(expected, Expected) and expected.evidence_id and task.suite != "finding":
        fail("only a finding task names the source its finding must cite")
    if isinstance(expected, Expected):
        check_expected(expected, fail)
    if isinstance(expected, ExpectedInput | ExpectedRun):
        check_journeys(expected.destinations, task.suite == "end-to-end", fail)
    if isinstance(expected, ExpectedRun):
        check_labels(expected.labels, fail)
        if missing := [str(p) for p in find_recordings(expected.recorded_as) if not p.exists()]:
            fail(f"no recording: {', '.join(missing)}")
    if (task.date == "today") != (task.suite in ("live investigation", "end-to-end")):
        fail("a live task, and only it, runs with the date of the trial")
    return Task(task.id, task.suite, None if task.date == "today" else task.date, inputs, expected)


def check_expected(expected: Expected, fail) -> None:
    scope = research_scope.load()
    if expected.identified_type not in [*scope.identified_types, None]:
        fail(f"unknown identified type {expected.identified_type!r}")
    if expected.status is not None and expected.status not in scope.finding_statuses:
        fail(f"unknown status {expected.status!r}")
    if (expected.outcome == "unidentified") != (expected.identified_type is None):
        fail("an object is unidentified exactly when it has no type")


def check_journeys(destinations: list[ExpectedDestination], end_to_end: bool, fail) -> None:
    """An end-to-end task gives the outcome of each journey there and back; the input loop plans
    none."""
    for destination in destinations:
        given = [destination.there is not None, destination.back is not None]
        if given != [end_to_end] * 2:
            fail("an end-to-end task, and only it, gives each destination there and back")


def find_recordings(name: str) -> list[Path]:
    """The fixtures that evals/label.py records at an end-to-end address under the name."""
    return [FIXTURES / folder / f"{name}.json" for folder in RECORDINGS]


def check_labels(labels: list[AddressLabel], fail) -> None:
    """Each label names an object once, in a category of the research scope, with a type and a
    status from its lists."""
    scope = research_scope.load()
    for field in ("id", "object_id"):
        values = [getattr(label, field) for label in labels]
        if duplicates := sorted({value for value in values if values.count(value) > 1}):
            fail(f"labels with the same {field}: {', '.join(duplicates)}")
    if all(label.left_out is not None for label in labels):
        fail("an end-to-end task needs a scored label")
    categories = {category.id for category in scope.categories}
    for label in labels:
        if label.category not in categories:
            fail(f"{label.id}: unknown category {label.category!r}")
        if label.left_out is None:
            outcome = "unidentified" if label.identified_type is None else "identified"
            check_expected(Expected(outcome, label.identified_type, label.status), fail)


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


def check_decision_state(state: InvestigationState, expected: TaskExpected | None, fail) -> None:
    """The model decides only under the cap, so an Enough task leaves a call; the page that it
    must read or leave is a result shown in the history and not read yet."""
    calls = [entry for entry in state.history if isinstance(entry, ToolCall)]
    if len(calls) >= TOOL_CAP:
        fail(f"{len(calls)} tool calls: at the cap of {TOOL_CAP}, the model decides nothing")
    for url in [expected.reads, expected.leaves_unread] if expected else []:
        if url is None:
            continue
        if url not in [page.url for page in state.pages]:
            fail(f"no page with the URL {url!r}")
        if url in [call.url for call in calls if call.tool == "extract"]:
            fail(f"the page {url!r} has been read already")


def read_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))
