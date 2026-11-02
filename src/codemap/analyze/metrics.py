"""Coupling and size metrics for modules and packages."""

from __future__ import annotations

from collections import defaultdict

from codemap.model import Edge, Metrics, Node


def apply_metrics(nodes: dict[str, Node], edges: list[Edge]) -> None:
    """Fill in module fan-in/fan-out, package roll-ups and instability.

    Only runtime imports between repository modules count. A package's fan-in
    and fan-out are the distinct modules across its boundary: outside modules
    importing into it, and outside modules it imports.
    """
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

    packages_of = {node.id: _packages(nodes, node) for node in nodes.values()}

    # Highest function complexity, rolled up to modules and packages.
    for node in nodes.values():
        complexity = node.metrics.complexity if node.metrics else None
        if node.kind not in ("function", "method") or not complexity:
            continue
        for owner in _owners(nodes, node):
            metrics = _metrics(owner)
            metrics.max_complexity = max(metrics.max_complexity or 0, complexity)

    package_in: dict[str, set[str]] = defaultdict(set)
    package_out: dict[str, set[str]] = defaultdict(set)
    for node in nodes.values():
        if node.kind != "module" or node.metrics is None:
            continue
        metrics = node.metrics
        metrics.fan_in = len(fan_in[node.id])
        metrics.fan_out = len(fan_out[node.id])
        metrics.instability = _instability(metrics.fan_in, metrics.fan_out)

        inside = packages_of[node.id]
        for package_id in inside:
            package = _metrics(nodes[package_id])
            package.loc = (package.loc or 0) + (metrics.loc or 0)
            package.symbols = (package.symbols or 0) + (metrics.symbols or 0)
        for target in fan_out[node.id]:
            target_packages = packages_of[target]
            for package_id in inside - target_packages:
                package_out[package_id].add(target)
            for package_id in target_packages - inside:
                package_in[package_id].add(node.id)

    for node in nodes.values():
        if node.kind == "package" and node.metrics is not None:
            node.metrics.fan_in = len(package_in[node.id])
            node.metrics.fan_out = len(package_out[node.id])
            node.metrics.instability = _instability(node.metrics.fan_in, node.metrics.fan_out)


def _metrics(node: Node) -> Metrics:
    if node.metrics is None:
        node.metrics = Metrics()
    return node.metrics


def _packages(nodes: dict[str, Node], node: Node) -> set[str]:
    result = set()
    parent = node.parent
    while parent is not None:
        if nodes[parent].kind == "package":
            result.add(parent)
        parent = nodes[parent].parent
    return result


def _owners(nodes: dict[str, Node], node: Node) -> list[Node]:
    """Containing modules and packages (classes are skipped)."""
    owners = []
    parent = node.parent
    while parent is not None:
        owner = nodes[parent]
        if owner.kind in ("module", "package"):
            owners.append(owner)
        parent = owner.parent
    return owners


def _instability(fan_in: int, fan_out: int) -> float | None:
    total = fan_in + fan_out
    return round(fan_out / total, 3) if total else None
