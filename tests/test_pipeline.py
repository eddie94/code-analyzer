import os
from pathlib import Path

import pytest

from codemap.model import Edge, Graph, dump_graph
from codemap.pipeline import analyze_repo

FIXTURE = Path(__file__).parent / "fixtures" / "shop"
SNAPSHOT = Path(__file__).parent / "snapshots" / "shop.json"


@pytest.fixture(scope="module")
def graph() -> Graph:
    graph = analyze_repo(FIXTURE, timestamp=False)
    graph.meta.root = "<fixture>"
    return graph


def imports(graph: Graph, source: str, target: str) -> Edge:
    matches = [
        e for e in graph.edges if (e.kind, e.source, e.target) == ("imports", source, target)
    ]
    assert len(matches) == 1, f"no import edge {source} -> {target}"
    return matches[0]


def test_snapshot(graph: Graph):
    """Set UPDATE_SNAPSHOTS=1 to accept intended output changes."""
    actual = dump_graph(graph) + "\n"
    if os.environ.get("UPDATE_SNAPSHOTS") or not SNAPSHOT.exists():
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(actual)
    assert actual == SNAPSHOT.read_text()


def test_deterministic(graph: Graph):
    again = analyze_repo(FIXTURE, timestamp=False, jobs=1)
    again.meta.root = "<fixture>"
    assert dump_graph(again) == dump_graph(graph)


def test_reexport_followed_to_definition(graph: Graph):
    edge = imports(graph, "mod:shop.services.billing", "mod:shop.models")
    assert edge.names == ["Order"]
    assert edge.via == ["mod:shop"]


def test_relative_and_submodule_imports(graph: Graph):
    assert imports(graph, "mod:shop.cycle_a", "mod:shop.cycle_b").names == ["cycle_b"]
    assert imports(graph, "mod:shop.notify", "mod:shop.services.billing").names == ["billing"]
    assert imports(graph, "mod:plugins.fancy", "mod:shop.models").names == ["models"]


def test_import_flags(graph: Graph):
    assert imports(graph, "mod:shop.models", "mod:shop.services.billing").type_only
    assert imports(graph, "mod:shop.services.billing", "mod:shop.notify").lazy
    assert imports(graph, "mod:shop.services.billing", "stdlib:json").conditional
    assert imports(graph, "mod:shop.services.billing", "external:ujson").conditional
    assert not imports(graph, "mod:shop.services.billing", "external:requests").conditional


def test_library_nodes(graph: Graph):
    kinds = {n.id: n.kind for n in graph.nodes}
    assert kinds["stdlib:json"] == "stdlib"
    assert kinds["external:requests"] == "external"
    assert "stdlib:__future__" not in kinds


def test_extends(graph: Graph):
    extends = {(e.source, e.target) for e in graph.edges if e.kind == "extends"}
    assert extends == {
        ("cls:shop.models.Order", "cls:shop.models.Base"),
        ("cls:plugins.fancy.FancyOrder", "cls:shop.models.Order"),
    }


def test_hierarchy(graph: Graph):
    nodes = {n.id: n for n in graph.nodes}
    assert nodes["mod:shop"].parent == "pkg:shop"
    assert nodes["mod:shop"].name == "__init__"
    assert nodes["mod:shop.services.billing"].parent == "pkg:shop.services"
    assert nodes["pkg:plugins"].path == "src/plugins"  # namespace package
    assert nodes["mod:tests.models_check"].path == "tests/models_check.py"
    assert nodes["meth:shop.services.billing.Invoice.pay"].parent == (
        "cls:shop.services.billing.Invoice"
    )
    assert nodes["meth:shop.services.billing.Invoice.pay"].is_async


def test_issues(graph: Graph):
    found = {(i.kind, tuple(i.nodes), i.runtime) for i in graph.issues}
    assert found == {
        ("cycle", ("mod:shop.cycle_a", "mod:shop.cycle_b"), True),
        ("cycle", ("mod:shop.models", "mod:shop.notify", "mod:shop.services.billing"), False),
        ("parse_error", ("mod:shop.broken",), None),
        ("unresolved_import", ("mod:shop.bad_import",), None),
    }
    unresolved = [i.line for i in graph.issues if i.kind == "unresolved_import"]
    assert unresolved == [1, 2, 3]


def test_metrics(graph: Graph):
    nodes = {n.id: n for n in graph.nodes}
    models = nodes["mod:shop.models"].metrics
    assert models is not None
    # fan-out ignores the TYPE_CHECKING import of billing
    assert (models.fan_in, models.fan_out) == (4, 0)
    assert nodes["meth:shop.models.Order.total"].metrics.complexity == 5

    package = nodes["pkg:shop"].metrics
    modules = [n for n in graph.nodes if n.kind == "module" and n.qualname.startswith("shop")]
    assert package.loc == sum(m.metrics.loc for m in modules if m.metrics)


def test_cycle_containing_runtime_cycle_is_reported_once():
    from codemap.analyze.cycles import find_cycles

    def edge(source: str, target: str, lazy: bool = False) -> Edge:
        return Edge(source=f"mod:{source}", target=f"mod:{target}", kind="imports", lazy=lazy)

    issues = find_cycles(
        [edge("a", "b"), edge("b", "a"), edge("b", "c"), edge("c", "a", lazy=True)]
    )
    assert [(i.nodes, i.runtime) for i in issues] == [(["mod:a", "mod:b"], True)]
