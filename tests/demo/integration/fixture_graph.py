"""Real application graph with fake external services. Never included in the runtime image."""

import os
import time
from pathlib import Path

import pytest

from demo.backend import graph_factory
from out_of_frame import agent, report
from tests.test_agent import stub_the_conversation, stub_the_sources
from tests.test_investigation import FakeWebSearch
from tests.test_report import FakeWriter

patch = pytest.MonkeyPatch()
stub_the_conversation(patch, {"Hello": None})
stub_the_sources(patch, overpass=[{"elements": [{"type": "count", "id": 0}] * 4}] * 50)
patch.setattr(report, "build_report_model", FakeWriter)
patch.setattr(graph_factory, "TavilyWebSearch", FakeWebSearch)
original_map = agent.get_map_objects


def paused_map(state):
    failure = os.environ.get("OUT_OF_FRAME_TEST_FAIL_FILE")
    if failure and Path(failure).exists():
        Path(failure).unlink()
        raise RuntimeError("PRIVATE_ERROR_PAYLOAD")
    marker = os.environ.get("OUT_OF_FRAME_TEST_PAUSE_FILE")
    if marker:
        Path(marker + ".started").touch()
        while Path(marker).exists():
            time.sleep(0.05)
    return original_map(state)


paused_map.__name__ = "get_map_objects"
patch.setattr(agent, "get_map_objects", paused_map)
graph = graph_factory.create_graph
