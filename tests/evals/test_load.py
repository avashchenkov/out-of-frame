"""Task format: every task parses and uses the research scope's lists. Expected results are checked
for their format only."""

import pytest
import yaml

from evals.graders.end_to_end import ExpectedRun
from evals.load import STATES, TASKS, Conversation, TaskFormatError, load
from out_of_frame.state import InvestigationState


def read(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write(path, data):
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


@pytest.mark.parametrize("path", sorted(TASKS.glob("*.yaml")), ids=lambda p: p.name)
def test_task_loads(path):
    load(path)


@pytest.mark.parametrize("kind", ["map", "plans"])
def test_a_live_task_starts_with_the_kind_of_its_object_source(tmp_path, kind):
    task = read(TASKS / "l1.yaml")
    task["input"]["sources"][0]["kind"] = kind
    inputs = load(write(tmp_path / "l1.yaml", task)).inputs
    assert isinstance(inputs, InvestigationState) and inputs.source_kind == kind


def set_label(field, value):
    return lambda task, state: task["expected"]["label"].__setitem__(field, value)


def set_object(field, value):
    return lambda task, state: task["input"]["map_object"].__setitem__(field, value)


def add_page(task, state):
    state["pages"].append(state["pages"][0] | {"id": "web-99"})


def repeat_last_call(task, state):
    state["history"] += state["history"][-2:]


def rename_page_to_map_source(task, state):
    state["pages"][0]["id"] = state["map_object"]["source_id"]
    state["history"][1]["pages"][0] = state["map_object"]["source_id"]


def drop_calls(task, state):
    state["history"] = [entry for entry in state["history"] if entry["role"] == "tool"]


BROKEN = [
    ("l1.yaml", set_label("identified_type", "no such type"), "unknown identified type"),
    ("l1.yaml", set_object("source_id", "other"), "one map or plans source of the task"),
    (
        "l1.yaml",
        lambda task, state: task["input"]["sources"][0].update(kind="web search"),
        "one map or plans source of the task",
    ),
    (
        "l1.yaml",
        lambda task, state: task["input"]["sources"].append(task["input"]["sources"][0]),
        "one map or plans source of the task",
    ),
    (
        "l1.yaml",
        lambda task, state: task["input"]["sources"][0].update(fixture="none.json"),
        "none.json",
    ),
    ("f1.yaml", lambda task, state: task["expected"].update(outcome="identified"), "exactly when"),
    ("f1.yaml", lambda task, state: task.update(date="today"), "a live task, and only it"),
    ("f1.yaml", add_page, "must be shown"),
    ("f1.yaml", repeat_last_call, "above the cap"),
    ("f1.yaml", rename_page_to_map_source, "same ID"),
    ("f1.yaml", drop_calls, "alternate"),
    ("f1.yaml", lambda task, state: task.update(expected={"flagged": True}), "only it"),
    (
        "p1.yaml",
        lambda task, state: task["expected"].update(outcome="unidentified"),
        "or flagged",
    ),
    ("p1.yaml", lambda task, state: task["input"].pop("page"), "a page"),
    ("t2.yaml", lambda task, state: task["input"].pop("map_object"), "triage task gives"),
    ("r4.yaml", lambda task, state: task.update(expected={"flagged": True}), "only it, has no"),
    (
        "r3.yaml",
        lambda task, state: state["findings"][0].update(map_object_id="osm-way-9"),
        "unknown object",
    ),
    (
        "r3.yaml",
        lambda task, state: state["findings"][0].update(evidence_id="web-9"),
        "unknown evidence",
    ),
    ("f2.yaml", lambda task, state: task["expected"].update(evidence_id="web-9"), "evidence_id"),
    (
        "l1.yaml",
        lambda task, state: task["expected"].update(evidence_id="web-1"),
        "evidence_id only with",
    ),
    (
        "t2.yaml",
        lambda task, state: task["expected"].update(evidence_id="overpass-1"),
        "only a finding task names",
    ),
    ("t2.yaml", lambda task, state: task.pop("expected"), "only it, has no"),
    ("i2.yaml", lambda task, state: task["input"].pop("messages"), "gives the user's messages"),
    ("t1.yaml", lambda task, state: task["input"].update(messages=["Hi"]), "user's messages"),
    (
        "i2.yaml",
        lambda task, state: task["input"]["sources"][0].update(kind="map"),
        "only geocoding",
    ),
    (
        "t1.yaml",
        lambda task, state: task.update(
            expected={"property": {"lat": 52.5, "lon": 13.1}, "destinations": []}
        ),
        "only it, expects the property and the destinations",
    ),
    ("i2.yaml", lambda task, state: task["expected"].pop("destinations"), "together"),
]


@pytest.mark.parametrize("name, change, error", BROKEN, ids=[error for _, _, error in BROKEN])
def test_a_broken_task_is_rejected(tmp_path, name, change, error):
    task = read(TASKS / name)
    state = read(STATES / task["input"]["state"]) if "state" in task["input"] else None
    change(task, state)
    if state is not None:
        task["input"]["state"] = str(write(tmp_path / "state.yaml", state))  # an absolute path
    with pytest.raises(TaskFormatError, match=error):
        load(write(tmp_path / "broken.yaml", task))


def test_a_yaml_error_is_a_format_error(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("id: [", encoding="utf-8")
    with pytest.raises(TaskFormatError, match="broken.yaml"):
        load(path)


def end_to_end_task() -> dict:
    """A small end-to-end task: one destination and one label of each kind."""
    label = {
        "id": "test-bakery",
        "object_id": "osm-way-1",
        "category": "industry",
        "coordinates": {"lat": 52.5, "lon": 13.4},
        "distance_tolerance_m": 100,
        "identified_type": "production",
        "status": "operating",
        "source_url": "https://example.org",
        "search": "Teststraße 1 Berlin",
    }
    skipped = {
        key: value
        for key, value in label.items()
        if key not in ("identified_type", "status", "source_url", "search")
    } | {"id": "test-yard", "object_id": "osm-way-2", "left_out": "no page a search finds"}
    return {
        "id": "E0",
        "suite": "end-to-end",
        "covers": "A test.",
        "date": "today",
        "input": {"messages": ["Teststraße 1, 10115 Berlin; I work at Work 1 from 8 to 17."]},
        "expected": {
            "property": {"lat": 52.5, "lon": 13.4},
            "destinations": [
                {
                    "coordinates": {"lat": 52.52, "lon": 13.41},
                    "leave_home": "08:00",
                    "leave_place": "17:00",
                    "there": "found",
                    "back": "found",
                }
            ],
            "labels": [label, skipped],
            "recorded_as": "e4-teutonenstrasse-10",
        },
    }


def test_an_end_to_end_task_gives_one_message_and_expects_its_labels(tmp_path):
    task = load(write(tmp_path / "e0.yaml", end_to_end_task()))
    assert isinstance(task.inputs, Conversation) and not task.inputs.sources
    assert isinstance(task.expected, ExpectedRun) and task.date is None
    assert [label.left_out for label in task.expected.labels] == [None, "no page a search finds"]


def set_first_label(field, value):
    return lambda task: task["expected"]["labels"][0].__setitem__(field, value)


BROKEN_END_TO_END = [
    (lambda task: task["input"]["messages"].append("Yes."), "one first message"),
    (
        lambda task: task["input"].update(sources=read(TASKS / "i3.yaml")["input"]["sources"]),
        "live sources",
    ),
    (lambda task: task["expected"]["destinations"][0].pop("back"), "there and back"),
    (set_first_label("category", "no such category"), "unknown category"),
    (set_first_label("status", "no such status"), "unknown status"),
    (set_first_label("object_id", "osm-way-2"), "same object_id"),
    (
        lambda task: [task["expected"].pop(key) for key in ("labels", "recorded_as")],
        "only it, expects labels",
    ),
    (lambda task: task.update(date="2026-10-16"), "a live task, and only it"),
    (lambda task: task["expected"].update(labels=task["expected"]["labels"][1:]), "scored label"),
    (lambda task: task["expected"].pop("recorded_as"), "the name they were recorded under"),
    (lambda task: task["expected"].update(recorded_as="nowhere"), "no recording"),
    (set_first_label("source_url", "TODO"), "address of its page"),
    (set_first_label("search", "TODO"), "fill in every TODO"),
]


@pytest.mark.parametrize(
    "change, error", BROKEN_END_TO_END, ids=[error for _, error in BROKEN_END_TO_END]
)
def test_a_broken_end_to_end_task_is_rejected(tmp_path, change, error):
    task = end_to_end_task()
    change(task)
    with pytest.raises(TaskFormatError, match=error):
        load(write(tmp_path / "broken.yaml", task))


def test_an_input_loop_task_gives_no_journeys(tmp_path):
    task = read(TASKS / "i1.yaml")
    task["expected"]["destinations"][0]["there"] = "found"
    with pytest.raises(TaskFormatError, match="there and back"):
        load(write(tmp_path / "broken.yaml", task))
