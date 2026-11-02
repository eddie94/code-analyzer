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
EdgeKind = Literal["imports", "extends", "calls"]
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


class FlowContext(_Model):
    kind: Literal["if", "else", "loop", "except", "with", "case"]
    # Condition or header as written; for "else", the condition it negates.
    text: str


class FlowStep(_Model):
    """One call in a function body, in source order, with what surrounds it."""

    line: int
    col: int = 0
    text: str  # the callee as written
    # Resolved functions or classes; several when it is one of a few candidates.
    targets: list[str] = Field(default_factory=list)
    library: str | None = None  # dotted library call, e.g. "asyncio.gather"
    confidence: Literal["exact", "inferred", "candidates"] | None = None
    awaited: bool = False
    context: list[FlowContext] = Field(default_factory=list)
    # Line of the asyncio.gather (or similar) call this runs inside, concurrently with
    # the other steps in the same group.
    group: int | None = None
    # Handed to create_task (or a function that does so): runs in the background.
    background: bool = False
    # Variables the result is assigned to.
    assigns: list[str] = Field(default_factory=list)
    # Variables of the function the arguments read: parameters, locals, `self.x`.
    inputs: list[str] = Field(default_factory=list)
    # The variable the method is called on, e.g. "self.client" for self.client.get().
    receiver: str | None = None
    # An argument of another call (not a concurrent or background one): its result feeds
    # that call directly instead of going through a variable.
    nested: bool = False


class FlowExit(_Model):
    kind: Literal["return", "raise"]
    line: int
    value: str = ""
    context: list[FlowContext] = Field(default_factory=list)
    # Variables the returned or raised value reads.
    inputs: list[str] = Field(default_factory=list)


class FlowSection(_Model):
    line: int
    title: str


class Flow(_Model):
    # Parameter names, without self and cls.
    params: list[str] = Field(default_factory=list)
    steps: list[FlowStep] = Field(default_factory=list)
    exits: list[FlowExit] = Field(default_factory=list)
    sections: list[FlowSection] = Field(default_factory=list)


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
    # Calls in this function that could not be followed, as written.
    unresolved_calls: list[str] = Field(default_factory=list)
    # Functions: calls, exits and step headings in source order.
    flow: Flow | None = None


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
    # Calls: at least one call is awaited.
    awaited: bool = False
    # Calls: exact (named directly), inferred (typed receiver), candidates (one of several).
    confidence: Literal["exact", "inferred", "candidates"] | None = None


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


class EntryPoint(_Model):
    kind: Literal["route", "startup", "main", "command", "script", "task"]
    # e.g. "POST /ask", "python src/app.py", "codemap"
    label: str
    target: str  # function node id
    app: str | None = None  # the App a route or hook is registered on


class App(_Model):
    """A web application or router object, e.g. `app = FastAPI()`."""

    id: str  # "app:<module>.<variable>"
    kind: Literal["fastapi", "starlette", "flask", "router", "blueprint"]
    name: str  # qualified variable name
    module: str  # module node id
    line: int | None = None
    # Routers mounted on this app with include_router / register_blueprint.
    includes: list[str] = Field(default_factory=list)


class Launch(_Model):
    """A way the code gets started: a server call in code or a command in a script."""

    kind: Literal["code", "command"]
    label: str  # e.g. "uvicorn.run(app)" or "uvicorn myapp.main:app --port 8000"
    target: str | None = None  # App id or function node id it starts
    source: str | None = None  # function node id, for "code"
    file: str | None = None  # repository-relative path, for "command"
    line: int | None = None


class SharedState(_Model):
    """A module global set in one function and read in others (e.g. built at startup)."""

    name: str  # qualified variable name
    writers: list[str]  # function node ids
    readers: list[str]
    types: list[str] = Field(default_factory=list)  # class node ids it may hold


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
    entrypoints: list[EntryPoint] = Field(default_factory=list)
    apps: list[App] = Field(default_factory=list)
    launches: list[Launch] = Field(default_factory=list)
    state: list[SharedState] = Field(default_factory=list)


def dump_graph(graph: Graph, compact: bool = False) -> str:
    """graph.json text; indented for files people diff, compact for the browser."""
    return graph.model_dump_json(
        indent=None if compact else 2, exclude_none=True, exclude_defaults=True
    )


def load_graph(path: Path) -> Graph:
    return Graph.model_validate_json(path.read_text(encoding="utf-8"))


def graph_schema() -> dict:
    return Graph.model_json_schema()


if __name__ == "__main__":
    import json

    print(json.dumps(graph_schema(), indent=2))
