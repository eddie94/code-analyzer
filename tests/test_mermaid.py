from pathlib import Path

import pytest

from codemap.model import Graph
from codemap.pipeline import analyze_repo
from codemap.render.mermaid import render_mermaid

FIXTURE = Path(__file__).parent / "fixtures" / "shop"


@pytest.fixture(scope="module")
def graph() -> Graph:
    return analyze_repo(FIXTURE, timestamp=False)


def node_id(text: str, label: str) -> str:
    label = label.replace("_", "#95;")
    line = next(
        line for line in text.splitlines() if f'"{label}"' in line and "subgraph" not in line
    )
    return line.strip().split("[")[0].split("(")[0]


def test_module_level(graph: Graph):
    result = render_mermaid(graph)
    text = result.text
    assert text.startswith("flowchart LR\n")
    assert any(
        line.strip().startswith("subgraph") and line.endswith('["shop.services"]')
        for line in text.splitlines()
    )
    assert "requests" not in text  # external hidden by default
    assert '"#95;#95;init#95;#95;"' in text

    a, b = node_id(text, "cycle_a"), node_id(text, "cycle_b")
    edges = [line.strip() for line in text.splitlines() if "-->" in line or "-.->" in line]
    assert f"{a} --> {b}" in edges and f"{b} --> {a}" in edges
    # import-time cycles are highlighted (cycle_a/cycle_b and shop/registry); the
    # TYPE_CHECKING and lazy one is not
    style = next(line for line in text.splitlines() if "linkStyle" in line)
    assert len(style.split()[1].split(",")) == 4

    models, billing = node_id(text, "models"), node_id(text, "billing")
    assert f"{models} -.-> {billing}" in edges  # TYPE_CHECKING import is dotted


def test_package_level_and_external(graph: Graph):
    text = render_mermaid(graph, level="package", include_external=True).text
    assert '[["shop.services"]]' in text
    assert '(["requests"])' in text
    assert '"cycle#95;a"' not in text


def test_focus(graph: Graph):
    text = render_mermaid(graph, focus="plugins").text
    assert '"fancy"' in text and '"models"' in text
    assert '"cycle#95;a"' not in text


def test_auto_collapse(graph: Graph):
    result = render_mermaid(graph, max_nodes=3)
    assert result.level == "package"
    assert result.warnings
