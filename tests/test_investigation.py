"""The investigation subgraph with a stubbed model and stubbed web search."""

import datetime as dt

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableBinding

from out_of_frame import finding, investigation
from out_of_frame.config import TOOL_CAP
from out_of_frame.state import Finding, Source, ToolCall, ToolResult
from out_of_frame.web_search import PageText, WebSearchError
from tests.test_finding import ANSWER, MAP_OBJECT, FakeModel

DATE = dt.date(2026, 10, 9)
SNIPPET = PageText("https://example.org", "Test GmbH makes parts at Teststraße 1.")
SEARCH = ("search", {"query": "Teststraße 1 Berlin"})


class FakeSearcher:
    """Makes the given tool calls in turn, then answers without one; keeps every request."""

    def __init__(self, *calls: tuple[str, dict]):
        self.calls = list(calls)
        self.requests = []

    def invoke(self, request):
        self.requests.append(request)
        if not self.calls:
            return AIMessage("The sources are enough.")
        name, args = self.calls.pop(0)
        return AIMessage("", tool_calls=[{"name": name, "args": args, "id": "toolu-1"}])


class FakeWebSearch:
    """Finds the same snippets for every search and the same text for every page read."""

    def __init__(self, snippets=(), page_text="", fails=False):
        self.snippets = list(snippets)
        self.page_text = page_text
        self.fails = fails

    def search(self, query):
        if self.fails:
            raise WebSearchError("the service is down")
        return self.snippets

    def extract(self, url):
        return [PageText(url, self.page_text)]


def investigate(monkeypatch, searcher, web_search, answer=ANSWER):
    """The investigation of MAP_OBJECT, and the finding model with the request it got, if any."""
    finder = FakeModel(answer)
    monkeypatch.setattr(investigation, "searcher", lambda: searcher)
    monkeypatch.setattr(finding, "finder", lambda: finder)
    return investigation.investigate(MAP_OBJECT, DATE, web_search), finder


def test_a_search_and_a_grounded_finding(monkeypatch):
    state, _ = investigate(monkeypatch, FakeSearcher(SEARCH), FakeWebSearch([SNIPPET]))
    assert state.history == [
        ToolCall(role="model", tool="search", query="Teststraße 1 Berlin"),
        ToolResult(role="tool", pages=["web-1"]),
    ]
    assert state.pages == [
        Source(
            id="web-1",
            kind="web search",
            request="Teststraße 1 Berlin",
            url="https://example.org",
            content="Test GmbH makes parts at Teststraße 1.",
        )
    ]
    assert state.finding == Finding.model_validate(ANSWER | {"map_object_id": "obj-1"})
    assert not state.web_search_failed


def test_the_model_sees_the_prompt_and_the_history_at_each_step(monkeypatch):
    searcher = FakeSearcher(SEARCH)
    state, _ = investigate(monkeypatch, searcher, FakeWebSearch([SNIPPET]))
    first, last = searcher.requests
    for request in first, last:
        assert isinstance(request[0], SystemMessage)
        assert f"at most {TOOL_CAP}" in request[0].content and "2026-10-09" in request[0].content
    assert len(first) == 2  # the prompt and the task
    assert last[1:] == finding.messages(state)


def test_pages_are_numbered_across_tool_calls(monkeypatch):
    other = PageText("https://example.com", "Test GmbH, Teststraße 1.")
    searcher = FakeSearcher(SEARCH, ("extract", {"url": "https://example.org"}))
    web_search = FakeWebSearch([SNIPPET, other], page_text="Test GmbH makes parts.")
    state, _ = investigate(monkeypatch, searcher, web_search)
    assert [page.id for page in state.pages] == ["web-1", "web-2", "web-3"]
    assert state.pages[2].request == "https://example.org"
    assert state.history[-1] == ToolResult(role="tool", pages=["web-3"])


def test_a_long_page_is_cut_and_says_so(monkeypatch):
    monkeypatch.setattr(investigation, "PAGE_CHARS", 10)
    searcher = FakeSearcher(("extract", {"url": "https://example.org"}))
    state, _ = investigate(monkeypatch, searcher, FakeWebSearch(page_text="x" * 11))
    assert state.pages[0].content == "x" * 10 + "\n[the page is cut at 10 characters]"


def test_at_the_cap_the_finding_is_written_without_asking_the_model_again(monkeypatch):
    searcher = FakeSearcher(*[SEARCH] * (TOOL_CAP + 2))
    state, finder = investigate(monkeypatch, searcher, FakeWebSearch([SNIPPET]))
    assert len(searcher.requests) == TOOL_CAP
    assert sum(isinstance(entry, ToolCall) for entry in state.history) == TOOL_CAP
    assert finder.request and state.finding is not None
    assert state.finding.outcome == "identified"


def test_a_finding_that_fails_the_grounding_check_makes_the_object_unidentified(monkeypatch):
    answer = ANSWER | {"key_facts": ["Test GmbH brews beer"]}
    state, _ = investigate(monkeypatch, FakeSearcher(SEARCH), FakeWebSearch([SNIPPET]), answer)
    assert state.finding == Finding.unidentified("obj-1")


def test_a_web_search_failure_ends_the_run_with_the_object_unidentified(monkeypatch):
    state, finder = investigate(monkeypatch, FakeSearcher(SEARCH), FakeWebSearch(fails=True))
    assert state.web_search_failed
    assert state.finding == Finding.unidentified("obj-1")
    assert finder.request == []  # no finding is drafted
    assert state.pages == []


def test_an_empty_search_result_is_not_a_failure(monkeypatch):
    state, _ = investigate(monkeypatch, FakeSearcher(SEARCH), FakeWebSearch([]))
    assert not state.web_search_failed
    assert state.history[-1] == ToolResult(role="tool", pages=[])


def test_the_model_may_stop_and_makes_one_tool_call_at_a_time():
    investigation.searcher.cache_clear()
    bound = investigation.searcher()
    assert isinstance(bound, RunnableBinding)
    search, extract = bound.kwargs["tools"]
    assert (search["name"], search["input_schema"]["required"]) == ("search", ["query"])
    assert (extract["name"], extract["input_schema"]["required"]) == ("extract", ["url"])
    assert bound.kwargs["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
