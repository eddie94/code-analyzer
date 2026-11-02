"""Render the import graph as a Mermaid flowchart."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

import networkx as nx

from codemap.model import Graph, Node

Level = Literal["package", "module"]
MAX_NODES = 300
_CYCLE_STYLE = "stroke:#d93025,stroke-width:2px"


@dataclass
class MermaidResult:
    text: str
    level: Level
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Units:
    ids: set[str]
    # (source, target) -> [import count, weak]; weak = only type-only or lazy imports
    edges: dict[tuple[str, str], list] = field(default_factory=dict)


def render_mermaid(
    graph: Graph,
    level: Level = "module",
    focus: str | None = None,
    include_external: bool = False,
    max_nodes: int = MAX_NODES,
) -> MermaidResult:
    nodes = {n.id: n for n in graph.nodes}
    warnings: list[str] = []
    units = _collect(graph, nodes, level, focus, include_external)
    if level == "module" and len(units.ids) > max_nodes:
        warnings.append(
            f"{len(units.ids)} modules exceed the limit of {max_nodes}; "
            "collapsed to package level (use --focus to narrow down)"
        )
        level = "package"
        units = _collect(graph, nodes, level, focus, include_external)
    return MermaidResult(_emit(units, nodes, level), level, warnings)


def _unit(node: Node, level: Level, include_external: bool) -> str | None:
    if node.kind in ("stdlib", "external"):
        return node.id if include_external else None
    if node.kind == "package" or level == "module":
        return node.id
    return node.parent or node.id


def _in_focus(node: Node, focus: str) -> bool:
    return node.qualname == focus or node.qualname.startswith(focus + ".")


def _collect(
    graph: Graph, nodes: dict[str, Node], level: Level, focus: str | None, include_external: bool
) -> _Units:
    units = _Units(ids=set())
    for node in graph.nodes:
        if node.kind == "module" and (focus is None or _in_focus(node, focus)):
            unit = _unit(node, level, include_external)
            if unit:
                units.ids.add(unit)

    for edge in graph.edges:
        if edge.kind != "imports":
            continue
        source = _unit(nodes[edge.source], level, include_external)
        target = _unit(nodes[edge.target], level, include_external)
        if source is None or target is None or source == target:
            continue
        if focus and not (_in_focus(nodes[source], focus) or _in_focus(nodes[target], focus)):
            continue
        units.ids.update((source, target))
        acc = units.edges.setdefault((source, target), [0, True])
        acc[0] += 1
        acc[1] = acc[1] and (edge.type_only or edge.lazy)
    return units


def _emit(units: _Units, nodes: dict[str, Node], level: Level) -> str:
    ids = {unit: f"n{i}" for i, unit in enumerate(sorted(units.ids))}
    lines = ["flowchart LR"]

    if level == "module":
        groups: dict[str | None, list[str]] = defaultdict(list)
        for unit in sorted(units.ids):
            node = nodes[unit]
            groups[node.parent if node.kind == "module" else None].append(unit)
        for index, parent in enumerate(sorted(groups, key=lambda p: p or "")):
            if parent is None:
                lines += [f"  {_shape(ids[u], nodes[u], qualified=True)}" for u in groups[parent]]
                continue
            lines.append(f'  subgraph g{index}["{_escape(nodes[parent].qualname)}"]')
            lines += [f"    {_shape(ids[u], nodes[u], qualified=False)}" for u in groups[parent]]
            lines.append("  end")
    else:
        lines += [f"  {_shape(ids[u], nodes[u], qualified=True)}" for u in sorted(units.ids)]

    solid = nx.DiGraph([pair for pair, (_, weak) in units.edges.items() if not weak])
    component = {
        member: i
        for i, group in enumerate(nx.strongly_connected_components(solid))
        if len(group) > 1
        for member in group
    }
    cyclic: list[str] = []
    for index, ((source, target), (count, weak)) in enumerate(sorted(units.edges.items())):
        arrow = "-.->" if weak else "-->"
        label = f"|{count}|" if level == "package" and count > 1 else ""
        lines.append(f"  {ids[source]} {arrow}{label} {ids[target]}")
        if not weak and source in component and component[source] == component.get(target):
            cyclic.append(str(index))
    if cyclic:
        lines.append(f"  linkStyle {','.join(cyclic)} {_CYCLE_STYLE}")
    return "\n".join(lines) + "\n"


def _shape(mermaid_id: str, node: Node, qualified: bool) -> str:
    label = _escape(node.qualname if qualified or node.kind != "module" else node.name)
    if node.kind == "package":
        return f'{mermaid_id}[["{label}"]]'
    if node.kind in ("stdlib", "external"):
        return f'{mermaid_id}(["{label}"])'
    return f'{mermaid_id}["{label}"]'


def _escape(text: str) -> str:
    # Underscores are escaped so `__init__` is not rendered as bold "init".
    return text.replace('"', "#quot;").replace("_", "#95;")
