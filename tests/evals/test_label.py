"""The labelling script on the recorded responses at Teutonenstraße 10, without live calls."""

import pytest
import yaml

from evals import label as labelling
from out_of_frame.state import Coordinates
from out_of_frame.web_search import PageText
from tests.evals.test_load import end_to_end_task

TEUTONENSTRASSE_10 = Coordinates(lat=52.4184654, lon=13.5426182)
JORDAN = "https://www.jordanshop.de/jordan-berlin-adlersholf"  # its website tag
XV_25 = "https://tk.gis-broker.de/metadata/bplan/begruendung/XV-25.pdf"  # its grund_www field


def test_the_recorded_data_hold_the_links_of_map_objects_and_plans():
    data = labelling.read_object_data("e4-teutonenstrasse-10", TEUTONENSTRASSE_10)
    assert JORDAN in data["osm-way-334170247"] and XV_25 in data["bplan-0915025"]


class FoundOnly:
    """A web search whose every search finds one page."""

    def __init__(self, url: str):
        self.url = url

    def search(self, query: str) -> list[PageText]:
        return [PageText(self.url + "/", "a snippet")]


def write_task(tmp_path, labels: list[dict]):
    task = end_to_end_task()
    task["expected"]["labels"] = labels
    path = tmp_path / "e0.yaml"
    path.write_text(yaml.safe_dump(task, allow_unicode=True), encoding="utf-8")
    return path


def a_label(object_id: str, source_url: str, search: str | None) -> dict:
    [first, _] = end_to_end_task()["expected"]["labels"]
    return (
        first
        | {"id": object_id, "object_id": object_id, "source_url": source_url}
        | {"search": search}
    )


@pytest.mark.parametrize(
    "labels, passed",
    [
        ([a_label("osm-way-334170247", JORDAN, None)], True),
        ([a_label("bplan-0915025", XV_25, None)], True),
        ([a_label("bplan-0915025", JORDAN, None)], False),
        ([a_label("osm-way-1", "https://example.org", "Teststraße 1 Berlin")], True),
        ([a_label("osm-way-1", "https://example.com", "Teststraße 1 Berlin")], False),
    ],
    ids=["map link", "plan link", "link of another object", "found", "not found"],
)
def test_check_needs_a_search_that_finds_the_page_or_a_link_in_the_data(
    tmp_path, monkeypatch, labels, passed
):
    monkeypatch.setattr(labelling, "TavilyWebSearch", lambda: FoundOnly("https://example.org"))
    assert labelling.check(write_task(tmp_path, labels)) == passed


@pytest.mark.parametrize(
    "corners, tolerance",
    [
        ([], 50),
        ([(52.4180, 13.5420), (52.4190, 13.5430)], 70),
        ([(52.4184, 13.5426), (52.4186, 13.5428)], 50),
    ],
    ids=["a node", "an area", "a small area"],
)
def test_a_tolerance_is_half_the_diagonal_and_at_least_the_minimum(corners, tolerance):
    assert labelling.measure_tolerance(TEUTONENSTRASSE_10, corners) == tolerance


class FoundOnTheSecondTry:
    """A web search whose results change from one call to the next, as Tavily's do."""

    def __init__(self):
        self.calls = 0

    def search(self, query: str) -> list[PageText]:
        self.calls += 1
        url = "https://example.org" if self.calls == 2 else "https://example.com"
        return [PageText(url, "a snippet")]


def test_a_search_counts_if_any_try_finds_the_page(tmp_path, monkeypatch):
    monkeypatch.setattr(labelling, "TavilyWebSearch", FoundOnTheSecondTry)
    labels = [a_label("osm-way-1", "https://example.org", "Teststraße 1 Berlin")]
    assert labelling.check(write_task(tmp_path, labels))
