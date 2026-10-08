"""Task format: every task parses and uses the research scope's lists. Expected results are checked
for their format only."""

import pytest
import yaml

from evals.load import STATES, TASKS, TaskFormatError, load


def read(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write(path, data):
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


@pytest.mark.parametrize("path", sorted(TASKS.glob("*.yaml")), ids=lambda p: p.name)
def test_task_loads(path):
    load(path)


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
    ("l1.yaml", set_object("source_id", "other"), "not among the task's sources"),
    (
        "l1.yaml",
        lambda task, state: task["input"]["sources"][0].update(fixture="none.json"),
        "none.json",
    ),
    ("f1.yaml", lambda task, state: task["expected"].update(outcome="identified"), "exactly when"),
    ("f1.yaml", lambda task, state: task.update(date="today"), "only a live task"),
    ("f1.yaml", add_page, "must be shown"),
    ("f1.yaml", repeat_last_call, "above the cap"),
    ("f1.yaml", rename_page_to_map_source, "same ID"),
    ("f1.yaml", drop_calls, "alternate"),
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
