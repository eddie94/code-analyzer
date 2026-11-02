"""Import cycle detection between modules."""

from __future__ import annotations

import networkx as nx

from codemap.model import Edge, Issue


def find_cycles(edges: list[Edge]) -> list[Issue]:
    """Report strongly connected groups of modules.

    A cycle is `runtime` when it exists among import-time imports alone. Cycles
    that need a TYPE_CHECKING or function-level import to close are reported
    separately at info level, since they cannot break module loading. A group
    that already contains a runtime cycle is not reported again.
    """
    eager = nx.DiGraph()
    every = nx.DiGraph()
    for edge in edges:
        if edge.kind != "imports" or not (
            edge.source.startswith("mod:") and edge.target.startswith("mod:")
        ):
            continue
        every.add_edge(edge.source, edge.target)
        if not (edge.type_only or edge.lazy):
            eager.add_edge(edge.source, edge.target)

    runtime = {frozenset(c) for c in nx.strongly_connected_components(eager) if len(c) > 1}
    issues = [
        Issue(
            kind="cycle",
            severity="warning",
            nodes=sorted(group),
            message=f"Import cycle across {len(group)} modules at import time",
            runtime=True,
        )
        for group in runtime
    ]
    for component in nx.strongly_connected_components(every):
        group = frozenset(component)
        if len(group) > 1 and not any(cycle <= group for cycle in runtime):
            issues.append(
                Issue(
                    kind="cycle",
                    severity="info",
                    nodes=sorted(group),
                    message=(
                        f"Import cycle across {len(group)} modules "
                        "through TYPE_CHECKING or function-level imports"
                    ),
                    runtime=False,
                )
            )
    return issues
