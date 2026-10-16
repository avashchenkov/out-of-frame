# /// script
# requires-python = ">=3.14"
# dependencies = ["tavily-python"]
# ///
"""Spike (roadmap step 10.2): do the label pages that the agent's search misses show up if
Tavily returns more results, or searches deeper?

Each case is a page that the label review found with other search engines and that the
agent's search, 5 results at basic depth, does not find. Search only, no model.

Exploratory code, outside the checks, never extended. Run:
uv run --env-file .env spikes/search-depth/spike.py
"""

import os

from tavily import TavilyClient

# The label, the search the labels make from what the agent sees, and parts of the URL of
# the page it misses.
CASES = [
    ("E2 NLND campus: LOXXESS", "Neuköllnische Allee 80 12057 Berlin", ["loxxess"]),
    ("E1 Klärwerkstraße 1: Sprenger", "Klärwerkstraße 1A 13597 Berlin", ["sprenger"]),
    ("E1 Klärwerkstraße 1: Sprenger", "Klärwerkstraße 1 13597 Berlin", ["sprenger"]),
    ("E4 Besenbinderstraße 23: AMR", "Besenbinderstraße 23 12524 Berlin", ["amr-shop"]),
    (
        "E2 Grenzallee 9-11: Leisten-Beyer",
        "Neuköllnische Allee 52 12057 Berlin",
        ["leisten-beyer.de"],
    ),
    (
        "E2 plan 8-81B: district report",
        "Bebauungsplan 8-81B",
        ["ausschussunterlagen/2023/dezember"],
    ),
    ("E1 line 6107: closed section", "Bahnstrecke Streckennummer 6107", ["vbb.de", "dbregio"]),
]
SETTINGS = [(5, "basic"), (20, "basic"), (20, "advanced")]  # the first is the agent's
RUNS = 2  # Tavily's results change from one call to the next


def main():
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    for label, query, wanted in CASES:
        print(f"{label}: {query!r}")
        for max_results, depth in SETTINGS:
            for run in range(1, RUNS + 1):
                answer = client.search(query, max_results=max_results, search_depth=depth)
                urls = [result["url"].lower() for result in answer["results"]]
                ranks = [i for i, url in enumerate(urls, 1) if any(w in url for w in wanted)]
                found = ", ".join(map(str, ranks)) or "not found"
                setting = f"{max_results:2} results, {depth:8} run {run}"
                print(f"  {setting}: {len(urls):2} back, {found}")


if __name__ == "__main__":
    main()
