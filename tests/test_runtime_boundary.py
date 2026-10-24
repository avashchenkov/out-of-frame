"""The reusable agent must not depend on demo, test or evaluation code/settings."""

import ast
from pathlib import Path

RUNTIME = Path(__file__).parents[1] / "src/out_of_frame"


def test_agent_imports_and_settings_exclude_demo_and_evaluation():
    for path in RUNTIME.rglob("*.py"):
        source = path.read_text()
        for node in ast.walk(ast.parse(source)):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            assert not any(
                name.split(".")[0] in ("demo", "tests", "evals", "pytest") for name in names
            ), path
        assert "OUT_OF_FRAME_JUDGE_" not in source, path
        assert "OUT_OF_FRAME_DEMO_" not in source, path
    assert not any((RUNTIME / "demo").rglob("*.py"))
