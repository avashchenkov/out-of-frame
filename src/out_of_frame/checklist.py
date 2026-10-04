"""The checklist in data/checklist.yaml: classes, their types, the statuses and the limits."""

from functools import cache
from importlib.resources import files
from typing import Any

import yaml

UNKNOWN = "unknown"


@cache
def load() -> dict[str, Any]:
    text = files("out_of_frame").joinpath("data/checklist.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def class_ids() -> list[str]:
    return [c["id"] for c in load()["classes"]]


def types(class_id: str) -> list[str]:
    """The types of a class; empty while they are not defined yet."""
    cls = next((c for c in load()["classes"] if c["id"] == class_id), None)
    if cls is None:
        raise ValueError(f"unknown class {class_id!r}")
    return list(cls.get("types", {}))


def statuses() -> list[str]:
    return list(load()["statuses"])


def tool_cap() -> int:
    return load()["investigation"]["tool_cap"]
