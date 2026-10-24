"""Wait for synchronous nodes too: cancelling their asyncio caller does not stop a thread."""

import asyncio
import threading
from collections import Counter
from dataclasses import replace
from functools import wraps

from langgraph.config import get_config

_lock = threading.Lock()
_active_nodes = Counter()
_blocked_threads = set()


def block_thread(thread_id: str) -> None:
    """Permanently refuse new nodes for a thread being deleted, including recovery."""
    with _lock:
        _blocked_threads.add(thread_id)


def has_active_nodes(thread_id: str | None = None) -> bool:
    """Include cancelled callers' sync nodes, for one thread or the whole process."""
    with _lock:
        return bool(_active_nodes) if thread_id is None else _active_nodes[thread_id] != 0


def wrap_node(context):
    """Supply run context and track nodes until they finish; passed to compile_graph()."""

    def wrap(function):
        @wraps(function)
        def run_node(*args, **kwargs):
            thread_id = get_config()["configurable"]["thread_id"]
            # Starting a node and blocking its thread must use the same lock.
            with _lock:
                if thread_id in _blocked_threads:
                    raise RuntimeError("conversation_unavailable")
                _active_nodes[thread_id] += 1
            try:
                if "runtime" in kwargs:
                    # Keep LangGraph's store, stream writer and execution metadata.
                    kwargs["runtime"] = replace(kwargs["runtime"], context=context)
                return function(*args, **kwargs)
            finally:
                with _lock:
                    _active_nodes[thread_id] -= 1
                    if not _active_nodes[thread_id]:
                        del _active_nodes[thread_id]

        return run_node

    return wrap


# The server sets this after startup cleanup. Recovered runs must wait for it.
startup_cleanup_finished = asyncio.Event()
