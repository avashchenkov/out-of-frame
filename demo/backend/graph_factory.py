"""Connect Aegra to the existing agent graph defined in out_of_frame.agent."""

import datetime as dt
from zoneinfo import ZoneInfo

from langchain_core.runnables import RunnableConfig
from langgraph_sdk.runtime import ServerRuntime

from demo.backend import activity, storage
from out_of_frame.agent import compile_graph
from out_of_frame.investigation import Context
from out_of_frame.web_search import TavilyWebSearch


async def create_graph(config: RunnableConfig, runtime: ServerRuntime):
    """Build the same agent graph for execution, state reads and schema inspection.

    For execution, recheck ownership and give nodes server-owned context and activity
    tracking so deletion can wait for them to stop. State reads and schema inspection
    need the same graph structure, without creating external clients.
    """
    node_wrapper = None
    if runtime.access_context == "threads.create_run":
        await activity.startup_cleanup_finished.wait()
        identity = runtime.user.identity
        identity_record = await storage.identity_row(identity)
        thread_id = config["configurable"]["thread_id"]
        if (
            not identity_record
            or identity_record["thread_id"] != thread_id
            or identity_record["deleting"]
            or identity_record["expires_at"] <= dt.datetime.now(dt.UTC)
        ):
            raise RuntimeError("conversation_unavailable")
        run_context = Context(dt.datetime.now(ZoneInfo("Europe/Berlin")).date(), TavilyWebSearch())
        node_wrapper = activity.wrap_node(run_context)

    # Aegra attaches its PostgreSQL checkpointer; None would create CLI memory storage.
    # Context comes from this factory, rather than from the client's request.
    return compile_graph(checkpointer=False, context_schema=None, node_wrapper=node_wrapper)
