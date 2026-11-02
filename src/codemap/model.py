"""graph.json schema.

These models are the single source of truth for the output format; the viewer's
TypeScript types are generated from their JSON Schema.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

NodeKind = Literal["package", "module", "class", "function", "method", "stdlib", "external"]
EdgeKind = Literal["imports", "extends"]
IssueKind = Literal["cycle", "unresolved_import", "parse_error", "layer_violation"]
Severity = Literal["error", "warning", "info"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Metrics(_Model):
    loc: int | None = None
    symbols: int | None = None
    fan_in: int | None = None
    fan_out: int | None = None
    # fan_out / (fan_in + fan_out); for packages, counted across the package boundary.
    instability: float | None = None
    complexity: int | None = None
    # Highest complexity among contained functions and methods.
    max_complexity: int | None = None
    # Commits touching the file in the last `Meta.churn_days` days (sum for packages).
    churn: int | None = None
    # churn x max_complexity (largest module value for packages).
    hotspot: int | None = None


class Node(_Model):
    id: str
    kind: NodeKind
    name: str
    qualname: str
    parent: str | None = None
    path: str | None = None
    range: tuple[int, int] | None = None
    doc: str | None = None
    decorators: list[str] = Field(default_factory=list)
    is_async: bool = False
    # Name of the configured layer a module belongs to.
    layer: str | None = None
    metrics: Metrics | None = None


class Edge(_Model):
    source: str
    target: str
    kind: EdgeKind
    names: list[str] = Field(default_factory=list)
    line: int | None = None
    # Only imported under `if TYPE_CHECKING:`.
    type_only: bool = False
    # Only imported inside function bodies.
    lazy: bool = False
    # Only imported inside try/if/loop blocks.
    conditional: bool = False
    # Modules that re-exported the imported names on the way to their definition.
    via: list[str] = Field(default_factory=list)


class Issue(_Model):
    kind: IssueKind
    severity: Severity
    nodes: list[str]
    message: str
    line: int | None = None
    # For cycles: True when the cycle exists among import-time imports.
    runtime: bool | None = None
    # For cycles: True when every cycle in the group passes through a package __init__.
    through_init: bool | None = None
    # For cycles: a few of the shortest concrete cycles, each as an ordered module list.
    examples: list[list[str]] = Field(default_factory=list)


class Meta(_Model):
    schema_version: int
    root: str
    source_roots: list[str]
    # Configured layer names, top (may import everything below) to bottom.
    layers: list[str] = Field(default_factory=list)
    # Window for churn metrics; None when git history was not used.
    churn_days: int | None = None
    generated_at: str | None = None


class Graph(_Model):
    meta: Meta
    nodes: list[Node]
    edges: list[Edge]
    issues: list[Issue]


def dump_graph(graph: Graph) -> str:
    return graph.model_dump_json(indent=2, exclude_none=True, exclude_defaults=True)


def load_graph(path: Path) -> Graph:
    return Graph.model_validate_json(path.read_text(encoding="utf-8"))


def graph_schema() -> dict:
    return Graph.model_json_schema()


if __name__ == "__main__":
    import json

    print(json.dumps(graph_schema(), indent=2))
