"""Web search on Tavily with a stubbed SDK client: what the model sees, retries and setup errors."""

from typing import get_args

import pytest
from tavily.errors import InvalidAPIKeyError
from tavily.errors import TimeoutError as TavilyTimeout

from out_of_frame import web_search
from out_of_frame.config import WEB_ATTEMPTS
from out_of_frame.state import ToolCall
from out_of_frame.web_search import PageText, TavilyWebSearch, WebSearchAccessError, WebSearchError

RESULT = {"url": "https://example.org", "title": "Test GmbH", "content": "Parts at Teststraße 1."}


class FakeClient:
    """Answers with the given answers in turn; an exception in the list is raised."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0

    def search(self, query, **settings):
        return self.answer()

    def extract(self, url, **settings):
        return self.answer()

    def answer(self):
        self.calls += 1
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def tavily(monkeypatch):
    """A Tavily client whose SDK client the test replaces; retries do not wait."""
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    monkeypatch.setattr(web_search.time, "sleep", lambda seconds: None)
    return TavilyWebSearch()


def test_a_snippet_starts_with_its_page_title(tavily):
    tavily.client = FakeClient({"results": [RESULT]})
    assert tavily.search("Teststraße 1") == [
        PageText("https://example.org", "Test GmbH\nParts at Teststraße 1.")
    ]


def test_a_page_that_tavily_cannot_read_gives_nothing(tavily):
    tavily.client = FakeClient({"results": [], "failed_results": [{"url": "https://x.org"}]})
    assert tavily.extract("https://x.org") == []


def test_a_failure_is_tried_again(tavily):
    tavily.client = FakeClient(TavilyTimeout(30), {"results": [RESULT]})
    assert len(tavily.search("Teststraße 1")) == 1 and tavily.client.calls == 2


def test_a_failure_on_every_try_is_a_web_search_failure(tavily):
    tavily.client = FakeClient(TavilyTimeout(30))
    with pytest.raises(WebSearchError):
        tavily.search("Teststraße 1")
    assert tavily.client.calls == WEB_ATTEMPTS


def test_a_refused_key_stops_at_once(tavily):
    tavily.client = FakeClient(InvalidAPIKeyError("invalid key"))
    with pytest.raises(WebSearchAccessError):
        tavily.search("Teststraße 1")
    assert tavily.client.calls == 1


def test_no_key_is_a_setup_error(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(WebSearchAccessError):
        TavilyWebSearch()


def test_the_tools_are_the_ones_that_a_written_history_can_name():
    names = get_args(ToolCall.model_fields["tool"].annotation)
    assert set(web_search.TOOLS) == set(names)
