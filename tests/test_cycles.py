import networkx as nx

from codemap.analyze.cycles import find_cycles, shortest_cycles
from codemap.model import Edge


def imports(*pairs: str, lazy: bool = False) -> list[Edge]:
    edges = []
    for pair in pairs:
        source, target = pair.split(">")
        edge = Edge(source=f"mod:{source}", target=f"mod:{target}", kind="imports", lazy=lazy)
        edges.append(edge)
    return edges


def summary(issues):
    return [(i.severity, i.nodes, i.runtime, i.through_init) for i in issues]


def test_direct_and_init_cycles_are_split():
    # pkg/__init__ imports a and b, both import pkg back, and a <-> c is a direct cycle.
    edges = imports(
        "pkg>pkg.a", "pkg>pkg.b", "pkg.a>pkg", "pkg.b>pkg", "pkg.a>pkg.c", "pkg.c>pkg.a"
    )
    issues = find_cycles(edges, {"mod:pkg"})
    assert summary(issues) == [
        ("warning", ["mod:pkg.a", "mod:pkg.c"], True, False),
        ("info", ["mod:pkg", "mod:pkg.a", "mod:pkg.b", "mod:pkg.c"], True, True),
    ]
    assert issues[0].examples == [["mod:pkg.a", "mod:pkg.c"]]
    # Examples of an __init__ cycle go through the __init__.
    assert issues[1].examples == [["mod:pkg", "mod:pkg.a"], ["mod:pkg", "mod:pkg.b"]]


def test_lazy_only_cycle_is_info():
    issues = find_cycles(imports("a>b") + imports("b>a", lazy=True), set())
    assert summary(issues) == [("info", ["mod:a", "mod:b"], False, None)]
    assert issues[0].examples == [["mod:a", "mod:b"]]


def test_shortest_cycles_are_deterministic_and_limited():
    graph = nx.DiGraph([("a", "b"), ("b", "c"), ("c", "a"), ("b", "a"), ("c", "d"), ("d", "c")])
    assert shortest_cycles(graph, graph.nodes) == [["a", "b"], ["c", "d"], ["a", "b", "c"]]
    assert shortest_cycles(graph, graph.nodes, limit=1) == [["a", "b"]]
