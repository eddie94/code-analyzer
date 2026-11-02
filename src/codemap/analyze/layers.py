"""Layer rules: higher layers may import lower ones, never the reverse."""

from __future__ import annotations

from fnmatch import fnmatchcase

from codemap.config import Layer
from codemap.model import Edge, Issue, Node


def module_matches(qualname: str, pattern: str) -> bool:
    """Glob over dotted names; `app.api.*` also covers the `app.api` package itself."""
    if fnmatchcase(qualname, pattern):
        return True
    return pattern.endswith(".*") and qualname == pattern[:-2]


def assign_layers(nodes: dict[str, Node], layers: list[Layer]) -> dict[str, int]:
    """Set `layer` on modules (first matching layer wins); return module id -> layer index."""
    assigned: dict[str, int] = {}
    for node in nodes.values():
        if node.kind != "module":
            continue
        for index, layer in enumerate(layers):
            if any(module_matches(node.qualname, p) for p in layer.modules):
                node.layer = layer.name
                assigned[node.id] = index
                break
    return assigned


def find_layer_violations(
    nodes: dict[str, Node], edges: list[Edge], layers: list[Layer]
) -> list[Issue]:
    """Imports from a lower layer into a higher one (layers are listed top to bottom).

    TYPE_CHECKING imports are ignored: they do not create a runtime dependency.
    """
    if not layers:
        return []
    assigned = assign_layers(nodes, layers)
    issues = []
    for edge in edges:
        if edge.kind != "imports" or edge.type_only:
            continue
        source = assigned.get(edge.source)
        target = assigned.get(edge.target)
        if source is None or target is None or source <= target:
            continue
        issues.append(
            Issue(
                kind="layer_violation",
                severity="error",
                nodes=[edge.source, edge.target],
                message=(
                    f"{nodes[edge.source].qualname} ({layers[source].name}) imports "
                    f"{nodes[edge.target].qualname} ({layers[target].name}), a higher layer"
                ),
                line=edge.line,
            )
        )
    return issues
