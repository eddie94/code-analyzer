"""scan -> extract -> resolve -> analyze, producing a `Graph`."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from codemap.analyze.cycles import find_cycles
from codemap.analyze.metrics import apply_metrics
from codemap.config import Config, load_config
from codemap.extract import ModuleInfo, extract_all
from codemap.model import SCHEMA_VERSION, Edge, Graph, Issue, Meta, Metrics, Node
from codemap.resolve import Resolver
from codemap.scan import ScanResult, SourceFile, scan_repo

_SYMBOL_PREFIX = {"class": "cls", "function": "fn", "method": "meth"}


def analyze_repo(
    repo: Path, config: Config | None = None, jobs: int | None = None, timestamp: bool = True
) -> Graph:
    repo = repo.resolve()
    config = config or load_config(repo)
    scan = scan_repo(repo, config)
    infos = extract_all(repo, scan.files, jobs)

    builder = _Builder(scan, infos)
    builder.build()
    issues = builder.issues + find_cycles(builder.edges())
    apply_metrics(builder.nodes, builder.edges())

    generated_at = datetime.now(UTC).isoformat(timespec="seconds") if timestamp else None
    return Graph(
        meta=Meta(
            schema_version=SCHEMA_VERSION,
            root=str(repo),
            source_roots=scan.source_roots,
            generated_at=generated_at,
        ),
        nodes=sorted(builder.nodes.values(), key=lambda n: n.id),
        edges=builder.edges(),
        issues=sorted(issues, key=lambda i: (i.kind, i.nodes, i.line or 0, i.message)),
    )


@dataclass
class _EdgeAcc:
    names: set[str] = field(default_factory=set)
    via: set[str] = field(default_factory=set)
    line: int | None = None
    # An edge is type-only/lazy/conditional only if every import behind it is.
    type_only: bool = True
    lazy: bool = True
    conditional: bool = True


class _Builder:
    def __init__(self, scan: ScanResult, infos: list[ModuleInfo]) -> None:
        self.scan = scan
        self.modules = {sf.module: (sf, info) for sf, info in zip(scan.files, infos, strict=True)}
        self.resolver = Resolver(self.modules, set(scan.packages))
        self.nodes: dict[str, Node] = {}
        self.issues: list[Issue] = []
        self._imports: dict[tuple[str, str], _EdgeAcc] = {}
        self._extends: set[tuple[str, str]] = set()

    def build(self) -> None:
        for name, directory in self.scan.packages.items():
            parent = name.rpartition(".")[0]
            self.nodes[f"pkg:{name}"] = Node(
                id=f"pkg:{name}",
                kind="package",
                name=name.rpartition(".")[2],
                qualname=name,
                parent=f"pkg:{parent}" if parent else None,
                path=directory,
            )
        for sf, info in self.modules.values():
            self._module(sf, info)
        for sf, info in self.modules.values():
            self._imports_of(sf, info)
            self._bases_of(sf, info)

    def edges(self) -> list[Edge]:
        edges = [
            Edge(
                source=source,
                target=target,
                kind="imports",
                names=sorted(acc.names),
                line=acc.line,
                type_only=acc.type_only,
                lazy=acc.lazy,
                conditional=acc.conditional,
                via=sorted(acc.via),
            )
            for (source, target), acc in self._imports.items()
        ]
        edges += [Edge(source=s, target=t, kind="extends") for s, t in self._extends]
        return sorted(edges, key=lambda e: (e.kind, e.source, e.target))

    def _module(self, sf: SourceFile, info: ModuleInfo) -> None:
        module_id = f"mod:{sf.module}"
        package = sf.module if sf.is_package else sf.module.rpartition(".")[0]
        self.nodes[module_id] = Node(
            id=module_id,
            kind="module",
            name="__init__" if sf.is_package else sf.module.rpartition(".")[2],
            qualname=sf.module,
            parent=f"pkg:{package}" if package else None,
            path=sf.path,
            range=(1, info.lines) if info.lines else None,
            doc=info.doc,
            metrics=None if info.error else Metrics(loc=info.loc, symbols=len(info.symbols)),
        )
        if info.error:
            self.issues.append(
                Issue(
                    kind="parse_error",
                    severity="error",
                    nodes=[module_id],
                    message=info.error,
                    line=info.error_line,
                )
            )
        for sym in info.symbols:
            owner = sym.qualname.rpartition(".")[0]
            node_id = f"{_SYMBOL_PREFIX[sym.kind]}:{sf.module}.{sym.qualname}"
            self.nodes[node_id] = Node(
                id=node_id,
                kind=sym.kind,
                name=sym.qualname.rpartition(".")[2],
                qualname=f"{sf.module}.{sym.qualname}",
                parent=f"cls:{sf.module}.{owner}" if owner else module_id,
                path=sf.path,
                range=sym.range,
                doc=sym.doc,
                decorators=sym.decorators,
                is_async=sym.is_async,
                metrics=Metrics(complexity=sym.complexity) if sym.complexity else None,
            )

    def _imports_of(self, sf: SourceFile, info: ModuleInfo) -> None:
        source = f"mod:{sf.module}"
        for imp in info.imports:
            for res in self.resolver.resolve_import(sf, imp):
                if res.problem:
                    self.issues.append(
                        Issue(
                            kind="unresolved_import",
                            severity="warning",
                            nodes=[source],
                            message=res.problem,
                            line=imp.line,
                        )
                    )
                if res.target is None or res.target == source:
                    continue
                self._ensure_library_node(res.target)
                acc = self._imports.setdefault((source, res.target), _EdgeAcc())
                acc.names.update(res.names)
                acc.via.update(res.via)
                acc.line = imp.line if acc.line is None else min(acc.line, imp.line)
                acc.type_only &= imp.type_only
                acc.lazy &= imp.lazy
                acc.conditional &= imp.conditional

    def _bases_of(self, sf: SourceFile, info: ModuleInfo) -> None:
        for sym in info.symbols:
            if sym.kind != "class":
                continue
            for base in sym.bases:
                target = self.resolver.resolve_class(sf.module, base)
                if target:
                    self._extends.add((f"cls:{sf.module}.{sym.qualname}", f"cls:{target}"))

    def _ensure_library_node(self, node_id: str) -> None:
        kind, _, name = node_id.partition(":")
        if kind in ("stdlib", "external") and node_id not in self.nodes:
            self.nodes[node_id] = Node(id=node_id, kind=kind, name=name, qualname=name)
