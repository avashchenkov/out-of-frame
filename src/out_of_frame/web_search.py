"""Web search for the investigation: the search and page-read calls behind the model's two
tools, run on Tavily. See docs/sources.md#tavily."""

import os
import time
from typing import Any, NamedTuple, Protocol

from langchain_core.tools import tool
from langgraph.runtime import get_runtime
from tavily import TavilyClient
from tavily.errors import ForbiddenError, InvalidAPIKeyError

from out_of_frame.config import SEARCH_RESULTS, WEB_ATTEMPTS


class PageText(NamedTuple):
    url: str
    content: str  # a snippet from a search, or the full text of a page


class WebSearchError(Exception):
    """Web search or a page read failed, after the client's own retries."""


class WebSearchAccessError(Exception):
    """The key is missing or refused, or its credits are used up. No investigation can work
    without it, so the run stops instead of marking every object unidentified. It is not a
    WebSearchError, so that the investigation does not catch it."""


class WebSearch(Protocol):
    """Tavily, or a stub in the tests. Each method raises WebSearchError if the service fails;
    nothing found is an empty list."""

    def search(self, query: str) -> list[PageText]: ...

    def extract(self, url: str) -> list[PageText]: ...


# The model's two tools. Each docstring is the tool's description for the model.
@tool
def search(query: str) -> list[PageText]:
    """Search the web. Returns short snippets."""
    return run_web_search().search(query)


@tool
def extract(url: str) -> list[PageText]:
    """Read the full text of one web page."""
    return run_web_search().extract(url)


def run_web_search() -> WebSearch:
    """The web search of the current investigation run, Tavily or a stub: a tool runs only
    inside the investigation subgraph, and its run context holds it."""
    context: Any = get_runtime().context  # the investigation's Context, which imports this module
    return context.web_search


TOOLS = {tool.name: tool for tool in [search, extract]}


class TavilyWebSearch:
    """Web search on the live web: Tavily search and extract, at their default basic depth."""

    def __init__(self):
        key = os.environ.get("TAVILY_API_KEY")
        if not key:  # without a key the client would quietly use Tavily's keyless limits
            raise WebSearchAccessError("TAVILY_API_KEY is not set")
        self.client = TavilyClient(api_key=key)

    def search(self, query: str) -> list[PageText]:
        """Each snippet starts with its page's title: a firm's name is often only there, and a
        key fact must be quoted word for word."""
        answer = call_tavily(self.client.search, query, max_results=SEARCH_RESULTS)
        return [
            PageText(result["url"], "\n".join(filter(None, [result["title"], result["content"]])))
            for result in answer["results"]
        ]

    def extract(self, url: str) -> list[PageText]:
        """A page that Tavily cannot read is not in its results, so the list is empty."""
        answer = call_tavily(self.client.extract, url)
        return [PageText(page["url"], page["raw_content"] or "") for page in answer["results"]]


def call_tavily(method, *args, **kwargs) -> dict:
    """Tavily's answer, tried again after a failure. A refused key is not tried again."""
    for attempt in range(1, WEB_ATTEMPTS + 1):
        try:
            return method(*args, **kwargs)
        except (InvalidAPIKeyError, ForbiddenError) as error:  # Forbidden includes no credits left
            raise WebSearchAccessError(f"Tavily refused the key: {error!r}") from error
        except Exception as error:  # a timeout, a rate limit or a server error
            if attempt == WEB_ATTEMPTS:
                raise WebSearchError(f"{WEB_ATTEMPTS} tries failed: {error!r}") from error
            time.sleep(attempt)
    raise ValueError("OUT_OF_FRAME_WEB_ATTEMPTS must be at least 1")
