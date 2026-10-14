"""The command line: a message in, such as an address or a listing, questions about what is
missing in the terminal, and the report out. Run with the keys in .env:
uv run --env-file .env out-of-frame "Freiheit 22, 13597 Berlin"
"""

import argparse
import datetime as dt
import logging
import os
import sys

import anthropic
import pydantic
from langchain_core.callbacks import get_usage_metadata_callback
from langgraph.types import Command

from out_of_frame import agent
from out_of_frame.conversation import ConversationError
from out_of_frame.finding import MissingFindingError
from out_of_frame.geocoding import GeocodingError
from out_of_frame.investigation import Context
from out_of_frame.prices import compute_run_cost
from out_of_frame.prompt_injection import PromptInjectionCheckError
from out_of_frame.report import ReportError
from out_of_frame.state import RunState
from out_of_frame.web_search import MeteredWebSearch, TavilyWebSearch, WebSearchAccessError

# What the user is told at once when a service fails after its retries, see
# docs/architecture.md#failures. The model never writes these.
FAILURE_NOTICES = {
    "map": "The map could not be loaded, so the report may be incomplete.",
    "plans": "Development plans could not be loaded, so the report may be incomplete.",
    "web search": "Web search failed, so an object may stay unidentified.",
}
# What each step has done, so that the user sees a run that takes a minute move. Steps that
# are not listed, such as filling in the references, are not told.
PROGRESS = {
    "get_map_objects": "Fetched the map.",
    "get_plans": "Fetched the development plans.",
    "triage_objects": "Checked the objects that the map makes clear.",
    "investigate_object": "Investigated an object on the web.",
    "write_report": "Wrote the report.",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check what lies around a Berlin address: industry, wastewater plants, "
        "airports, major roads and railways, and development plans."
    )
    parser.add_argument(
        "message",
        help='the property to check: an address, such as "Freiheit 22, 13597 Berlin", or a '
        "listing; the agent asks for what is missing",
    )
    args = parser.parse_args()
    if not args.message.strip():  # the model gets no empty message
        parser.error("give an address or a listing")
    logging.basicConfig(format="%(levelname)s %(name)s: %(message)s")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        parser.exit(1, "Set ANTHROPIC_API_KEY, for example in .env: see .env.example.\n")
    try:
        web_search = MeteredWebSearch(TavilyWebSearch())
    except WebSearchAccessError as error:
        parser.exit(1, f"Set TAVILY_API_KEY, for example in .env: {error}\n")
    with get_usage_metadata_callback() as usage:
        try:
            state = run(args.message, web_search)
        except EOFError:
            parser.exit(2, "\nNo answer, so the run stops.\n")
        except WebSearchAccessError as error:
            parser.exit(1, f"Web search does not accept the key: {error}\n")
        except (
            GeocodingError,
            anthropic.APIError,
            pydantic.ValidationError,  # a model answer outside its schema, such as an unknown type
            PromptInjectionCheckError,
            ConversationError,
            MissingFindingError,
            ReportError,
        ) as error:
            # A failed model call or geocoding stops the run, see docs/architecture.md#failures.
            parser.exit(1, f"The run stopped: {error}. Try again later.\n")
        else:
            print(state.report)
        finally:  # a run that stops has paid for its calls too
            cost = compute_run_cost(usage.usage_metadata, web_search.credits)
            print(f"Tool calls: {web_search.tool_calls}, cost: ${cost:.4f}", file=sys.stderr)


def run(message: str, web_search: MeteredWebSearch) -> RunState:
    """The run, with each question asked on stderr and answered on stdin, and its progress and
    each failed service told on stderr as they happen: stdout holds only the report."""
    graph, config = agent.build_graph(), agent.start_thread()
    command: RunState | Command = agent.start(message)
    while True:
        context = Context(dt.date.today(), web_search)  # today's, after an answer days later
        for chunk in graph.stream(command, config, context=context, stream_mode="updates"):
            for node, update in chunk.items():
                tell_progress(node, update)
        question = agent.find_question(graph, config)
        if question is None:
            return RunState.model_validate(graph.get_state(config).values)
        print(question, file=sys.stderr)
        command = Command(resume=read_answer())


def tell_progress(node: str, update) -> None:
    """What the step has done and each service it found failed, on stderr."""
    if not isinstance(update, dict):  # the question the run waits on, or no update
        return
    if node in PROGRESS and set(update) != {"failures"}:  # not "fetched" if it failed
        print(PROGRESS[node], file=sys.stderr)
    for service in update.get("failures", []):
        print(FAILURE_NOTICES[service], file=sys.stderr)


def read_answer() -> str:
    """The user's answer, asked for again while it is empty: the model gets no empty message."""
    answer = ""
    while not answer.strip():
        print("> ", end="", file=sys.stderr, flush=True)
        answer = input()
    return answer
