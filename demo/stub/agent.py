"""A stand-in for the agent, for trying the Web UI locally without model or web calls.

Only the local UI stack loads it, through its own Aegra config, see demo/README.md. The
runtime image and its config never include it.

It has the real graph's steps, so the page shows the same progress, question, retry and
report. Each step waits about three seconds instead of working, and the investigations end
about one a second. The report is a full recorded example, under the user's address. Words in
the user's messages choose other paths: "fail" adds source failures, and "crash" stops the
first run with an error so that it can be retried.
"""

import hashlib
import json
import operator
import os
import re
import threading
import time
from functools import cache
from pathlib import Path
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_config
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Send, interrupt
from langgraph_sdk.runtime import ServerRuntime

from demo.backend import graph_factory

# How long the steps wait, as a scale: 1 for about three seconds a step, 0 for none.
DELAY = float(os.environ.get("OUT_OF_FRAME_DEMO_STUB_DELAY", "1"))

EXAMPLES = Path(__file__).parents[1] / "frontend" / "src" / "data" / "recorded-examples.json"
RESEARCH_STARTS = ["get_map_objects", "get_plans", "plan_journeys"]
# One or two capitalised words before a house number, such as "Karl-Marx-Allee 3" or
# "Oberhofer Weg 45, 12209 Berlin".
ADDRESS = re.compile(r"(?:[A-ZÄÖÜ][\w.\-]*\s){1,2}\d+\s?[a-zA-Z]?\b(?:,\s*\d{5})?(?:,?\s*Berlin)?")
FILLER = re.compile(r"\b(?:please\s+)?check\b", re.IGNORECASE)
TRIPS = re.compile(r"travel|work|nowhere|commute|school|office", re.IGNORECASE)

# The threads whose first run has crashed, so that their retry goes through.
_crashed: set[str] = set()
_lock = threading.Lock()


class StubState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    failures: Annotated[list[str], operator.add]


def wait(seconds: float) -> None:
    time.sleep(seconds * DELAY)


def said(state: StubState) -> str:
    return " ".join(m.text for m in state["messages"] if isinstance(m, HumanMessage))


def find_address(state: StubState) -> str | None:
    match = ADDRESS.search(FILLER.sub("", said(state)))
    return match.group(0).strip(" ,") if match else None


def missing(state: StubState) -> str | None:
    """At most one question, so that any answer leads on to the report. The address question
    comes only when the message has no number at all."""
    if sum(isinstance(m, HumanMessage) for m in state["messages"]) > 1:
        return None
    if not re.search(r"\d", said(state)):
        return "Which address in Berlin should I check? Please give the street and house number."
    if not TRIPS.search(said(state)):
        return (
            "Where do you travel regularly from this address, such as to work or school, "
            "and at what times? If nowhere, just say so."
        )
    return None


async def create_graph(config: RunnableConfig, runtime: ServerRuntime):
    """Aegra's entry point, as demo/backend/graph_factory.py is for the real agent: the same
    ownership checks and activity tracking, without the real agent's context."""
    node_wrapper = await graph_factory.wrap_for_run(config, runtime, lambda: None)
    return compile_graph(checkpointer=False, node_wrapper=node_wrapper)


def compile_graph(*, checkpointer=None, node_wrapper=None):
    """The stub with the real agent's steps and edges, see out_of_frame.agent.compile_graph."""
    builder = StateGraph(StubState)
    wrap = node_wrapper or (lambda node: node)
    for node in (
        extract_input,
        detect_language,
        geocode_input,
        ask_for_missing,
        wait_for_answer,
        get_map_objects,
        get_plans,
        plan_journeys,
        triage_objects,
        get_addresses,
        investigate_object,
        write_report,
        fill_references,
    ):
        builder.add_node(wrap(node))
    builder.add_edge(START, "extract_input")
    builder.add_edge("extract_input", "detect_language")
    builder.add_edge("detect_language", "geocode_input")
    builder.add_conditional_edges(
        "geocode_input",
        lambda state: "ask_for_missing" if missing(state) else RESEARCH_STARTS,
        ["ask_for_missing", *RESEARCH_STARTS],
    )
    builder.add_edge("ask_for_missing", "wait_for_answer")
    builder.add_edge("wait_for_answer", "extract_input")
    builder.add_edge(RESEARCH_STARTS, "triage_objects")
    builder.add_edge("triage_objects", "get_addresses")
    # The stub always investigates, but keeps the real graph's way past research.
    builder.add_conditional_edges(
        "get_addresses", send_each_object, ["investigate_object", "write_report"]
    )
    builder.add_edge("investigate_object", "write_report")
    builder.add_edge("write_report", "fill_references")
    builder.add_edge("fill_references", END)
    return builder.compile(checkpointer=checkpointer).with_config(max_concurrency=3)


def extract_input(state: StubState) -> dict:
    wait(1.5)
    return {}


def detect_language(state: StubState) -> dict:
    wait(1.5)
    return {}


def geocode_input(state: StubState) -> dict:
    wait(3)
    return {}


def ask_for_missing(state: StubState) -> dict:
    wait(2)
    return {"messages": [AIMessage(missing(state))]}


def wait_for_answer(state: StubState) -> dict:
    return {"messages": [HumanMessage(interrupt(state["messages"][-1].text))]}


def get_map_objects(state: StubState) -> dict:
    thread = get_config()["configurable"]["thread_id"]
    with _lock:
        crash = "crash" in said(state).lower() and thread not in _crashed
        _crashed.add(thread)
    wait(3)
    if crash:
        raise RuntimeError("stub crash, as the message asked")
    return {}


def get_plans(state: StubState) -> dict:
    wait(2.5)
    return {}


def plan_journeys(state: StubState) -> dict:
    wait(3.5)
    return {"failures": ["transit"] if "fail" in said(state).lower() else []}


def triage_objects(state: StubState) -> dict:
    wait(3)
    return {}


def get_addresses(state: StubState) -> dict:
    wait(3)
    return {}


def send_each_object(state: StubState) -> list[Send]:
    """12 to 20 investigations, always the same number for one address."""
    count = 12 + hashlib.sha256((find_address(state) or "").encode()).digest()[0] % 9
    return [Send("investigate_object", {"index": index}) for index in range(count)]


def investigate_object(payload: dict) -> dict:
    # Two to four seconds, three at once, so that about one object ends each second.
    wait(2 + payload["index"] * 7 % 5 * 0.5)
    return {}


def write_report(state: StubState) -> dict:
    wait(3)
    failed = "fail" in said(state).lower()
    return {"failures": ["web search"] if failed else []}


def fill_references(state: StubState) -> dict:
    wait(1)
    return {"messages": [AIMessage(choose_report(state), id="final-report")]}


def choose_report(state: StubState) -> str:
    """A full recorded report: the address's own if it is a recorded example; else the one with
    journeys if the user travels somewhere, or the longest one if not, under the user's
    address."""
    text = said(state).lower()
    examples = {example["id"]: example for example in recorded_examples()}
    own = next((e for e in examples.values() if e["title"].lower() in text), None)
    travels = "nowhere" not in text
    example = own or examples["teutonenstrasse-10" if travels else "corinthstrasse-60"]
    report = next(m["content"] for m in example["messages"] if m["id"] == "final-report")
    if own:
        return report
    address = find_address(state) or "the address"
    body = report.split("\n", 1)[1]
    return f"# What lies around {address}\n{body}"


@cache
def recorded_examples() -> list[dict]:
    return json.loads(EXAMPLES.read_text(encoding="utf-8"))
