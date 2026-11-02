"""Module fan-in/fan-out and package roll-ups."""

from __future__ import annotations

from collections import defaultdict

from codemap.model import Edge, Metrics, Node


def apply_metrics(nodes: dict[str, Node], edges: list[Edge]) -> None:
    fan_in: dict[str, set[str]] = defaultdict(set)
    fan_out: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if (
            edge.kind == "imports"
            and not edge.type_only
            and edge.source.startswith("mod:")
            and edge.target.startswith("mod:")
        ):
            fan_out[edge.source].add(edge.target)
            fan_in[edge.target].add(edge.source)

    for node in nodes.values():
        if node.kind != "module" or node.metrics is None:
            continue
        node.metrics.fan_in = len(fan_in[node.id])
        node.metrics.fan_out = len(fan_out[node.id])

        parent = node.parent
        while parent is not None:
            package = nodes[parent]
            if package.metrics is None:
                package.metrics = Metrics(loc=0, symbols=0)
            package.metrics.loc = (package.metrics.loc or 0) + (node.metrics.loc or 0)
            package.metrics.symbols = (package.metrics.symbols or 0) + (node.metrics.symbols or 0)
            parent = package.parent
