"""Import cycle detection between modules."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

import networkx as nx

from codemap.model import Edge, Issue

MAX_EXAMPLES = 3
# Upper bound on BFS starts per group; plenty to find the shortest cycles.
_MAX_STARTS = 400


def find_cycles(edges: list[Edge], package_modules: set[str]) -> list[Issue]:
    """Report strongly connected groups of modules.

    Import-time cycles are split in two. Direct cycles survive when package
    `__init__` modules are left out; they are warnings. The rest only close
    through an `__init__` (a submodule importing its own package, which
    re-exports it) - an idiomatic pattern reported at info level.

    Cycles that need a TYPE_CHECKING or function-level import to close are also
    info, since they cannot break module loading. A group that already contains
    an import-time cycle is not reported again.
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

    issues: list[Issue] = []
    runtime = [frozenset(c) for c in nx.strongly_connected_components(eager) if len(c) > 1]
    for group in runtime:
        inits = group & package_modules
        direct = eager.subgraph(group - inits)
        for component in nx.strongly_connected_components(direct):
            if len(component) > 1:
                issues.append(
                    _issue(
                        direct,
                        component,
                        "warning",
                        f"Import cycle across {len(component)} modules at import time",
                        runtime=True,
                        through_init=False,
                    )
                )
        if inits:
            issues.append(
                _issue(
                    eager,
                    group,
                    "info",
                    f"Import cycle across {len(group)} modules through package __init__ imports",
                    runtime=True,
                    through_init=True,
                    starts=inits,
                )
            )

    for component in nx.strongly_connected_components(every):
        if len(component) > 1 and not any(group <= component for group in runtime):
            issues.append(
                _issue(
                    every,
                    component,
                    "info",
                    f"Import cycle across {len(component)} modules "
                    "through TYPE_CHECKING or function-level imports",
                    runtime=False,
                )
            )
    return issues


def _issue(
    graph: nx.DiGraph,
    members: Iterable[str],
    severity: str,
    message: str,
    *,
    runtime: bool,
    through_init: bool | None = None,
    starts: Iterable[str] | None = None,
) -> Issue:
    members = set(members)
    return Issue(
        kind="cycle",
        severity=severity,
        nodes=sorted(members),
        message=message,
        runtime=runtime,
        through_init=through_init,
        examples=shortest_cycles(graph.subgraph(members), starts or members),
    )


def shortest_cycles(
    graph: nx.DiGraph, starts: Iterable[str], limit: int = MAX_EXAMPLES
) -> list[list[str]]:
    """The `limit` shortest distinct cycles that pass through any of `starts`.

    For each start, every outgoing edge is closed by the shortest path back, so
    one start can contribute several cycles. Each cycle is rotated to begin at
    its smallest module id, so the output is deterministic.
    """
    found: set[tuple[str, ...]] = set()
    for start in sorted(starts)[:_MAX_STARTS]:
        for cycle in _cycles_through(graph, start):
            pivot = cycle.index(min(cycle))
            found.add(tuple(cycle[pivot:] + cycle[:pivot]))
    return [list(c) for c in sorted(found, key=lambda c: (len(c), c))[:limit]]


def _cycles_through(graph: nx.DiGraph, start: str) -> list[list[str]]:
    # Reverse BFS: toward[x] is the next hop on a shortest path from x to start.
    toward: dict[str, str] = {}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for predecessor in sorted(graph.predecessors(node)):
            if predecessor != start and predecessor not in toward:
                toward[predecessor] = node
                queue.append(predecessor)

    cycles = []
    for successor in sorted(graph.successors(start)):
        if successor == start or successor not in toward:
            continue
        cycle = [start, successor]
        while toward[cycle[-1]] != start:
            cycle.append(toward[cycle[-1]])
        cycles.append(cycle)
    return cycles
