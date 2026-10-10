"""The command line: an address in, the report out. Run with the keys in .env:
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

from out_of_frame import agent
from out_of_frame.agent import UnclearAddressError
from out_of_frame.finding import MissingFindingError
from out_of_frame.geocoding import GeocodingError
from out_of_frame.investigation import Context
from out_of_frame.prices import compute_run_cost
from out_of_frame.prompt_injection import PromptInjectionCheckError
from out_of_frame.report import ReportError
from out_of_frame.state import Address, RunState
from out_of_frame.web_search import MeteredWebSearch, TavilyWebSearch, WebSearchAccessError

# What the user is told at once when a service fails after its retries, see
# docs/architecture.md#failures. The model never writes these.
FAILURE_NOTICES = {
    "map": "The map could not be loaded, so the report may be incomplete.",
    "web search": "Web search failed, so an object may stay unidentified.",
}
# What each step has done, so that the user sees a run that takes a minute move.
PROGRESS = {
    "geocode_property": "Found the address.",
    "get_map_objects": "Fetched the map.",
    "investigate_object": "Investigated an object on the web.",
    "write_report": "Wrote the report.",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check what lies around a Berlin address: industry, wastewater plants, "
        "airports, major roads and railways."
    )
    parser.add_argument("address", help='a precise address, such as "Freiheit 22, 13597 Berlin"')
    args = parser.parse_args()
    logging.basicConfig(format="%(levelname)s %(name)s: %(message)s")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        parser.exit(1, "Set ANTHROPIC_API_KEY, for example in .env: see .env.example.\n")
    try:
        web_search = MeteredWebSearch(TavilyWebSearch())
    except WebSearchAccessError as error:
        parser.exit(1, f"Set TAVILY_API_KEY, for example in .env: {error}\n")
    with get_usage_metadata_callback() as usage:
        try:
            state = run(args.address, web_search)
        except UnclearAddressError:
            parser.exit(
                2,
                f"No single building in Berlin matches {args.address!r}: give the "
                "street, the house number and the postcode.\n",
            )
        except WebSearchAccessError as error:
            parser.exit(1, f"Web search does not accept the key: {error}\n")
        except (
            GeocodingError,
            anthropic.APIError,
            pydantic.ValidationError,  # a model answer outside its schema, such as an unknown type
            PromptInjectionCheckError,
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


def run(address: str, web_search: MeteredWebSearch) -> RunState:
    """The run, with its progress and each failed service told on stderr as they happen."""
    start = RunState(property=Address(text=address))
    context = Context(dt.date.today(), web_search)
    end: dict = {}
    for mode, chunk in agent.build_graph().stream(
        start, context=context, stream_mode=["updates", "values"]
    ):
        assert isinstance(chunk, dict)  # an update by node name, or the whole state
        if mode == "values":
            end = chunk
            continue
        for node, update in chunk.items():
            print(PROGRESS.get(node, node), file=sys.stderr)
            for service in (update or {}).get("failures", []):
                print(FAILURE_NOTICES[service], file=sys.stderr)
    return RunState.model_validate(end)
