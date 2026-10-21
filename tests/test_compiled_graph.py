"""docs/compiled-graph.md shows the graphs as the code compiles them. If this test fails, replace
the page's mermaid blocks with the output of: uv run python -m tests.test_compiled_graph"""

from pathlib import Path

from out_of_frame import agent, investigation

PAGE = Path(__file__).parents[1] / "docs" / "compiled-graph.md"


def draw() -> list[str]:
    """Each graph as LangGraph draws it, in a mermaid block."""
    graphs = [agent.build_graph(), investigation.build_graph()]
    return [f"```mermaid\n{graph.get_graph().draw_mermaid()}```\n" for graph in graphs]


def test_the_page_shows_the_graphs_that_the_code_compiles():
    page = PAGE.read_text(encoding="utf-8")
    for block in draw():
        assert block in page, __doc__


if __name__ == "__main__":
    print("\n".join(draw()))
