"""Per-file extraction with the standard `ast` module.

Nothing here looks at other files: imports are recorded as written and resolved
later by `codemap.resolve`.
"""

from __future__ import annotations

import ast
import io
import tokenize
import warnings
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from codemap.scan import SourceFile

PARALLEL_THRESHOLD = 64

_BRANCHES = (
    ast.If,
    ast.IfExp,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.ExceptHandler,
    ast.match_case,
    ast.comprehension,
)
_NON_CODE_TOKENS = {
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.ENCODING,
    tokenize.ENDMARKER,
}


@dataclass
class RawImport:
    module: str | None  # as written; None for `from . import x`
    level: int  # number of leading dots
    names: list[tuple[str, str | None]] | None  # (name, asname); None for plain `import`
    alias: str | None  # `import a.b as alias`
    line: int
    module_level: bool  # binds a name in the module namespace
    type_only: bool
    lazy: bool
    conditional: bool


@dataclass
class Symbol:
    kind: Literal["class", "function", "method"]
    qualname: str  # relative to the module, e.g. "Outer.method"
    range: tuple[int, int]
    doc: str | None = None
    decorators: list[str] = field(default_factory=list)
    bases: list[list[str]] = field(default_factory=list)  # dotted parts, e.g. ["models", "Base"]
    is_async: bool = False
    complexity: int | None = None


@dataclass
class ModuleInfo:
    lines: int = 0
    loc: int = 0
    doc: str | None = None
    all_names: list[str] | None = None
    defined: set[str] = field(default_factory=set)  # names defined (not imported) at module level
    imports: list[RawImport] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    error: str | None = None
    error_line: int | None = None


@dataclass(frozen=True)
class _Ctx:
    type_only: bool = False
    lazy: bool = False  # inside a function body
    conditional: bool = False


def extract_all(root: Path, files: list[SourceFile], jobs: int | None = None) -> list[ModuleInfo]:
    paths = [root / f.path for f in files]
    if jobs == 1 or len(paths) < PARALLEL_THRESHOLD:
        return [parse_file(p) for p in paths]
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(parse_file, paths, chunksize=32))


def parse_file(path: Path) -> ModuleInfo:
    try:
        source = path.read_bytes()
    except OSError as e:
        return ModuleInfo(error=f"cannot read file: {e.strerror}")
    return parse_source(source, str(path))


def parse_source(source: bytes, filename: str = "<source>") -> ModuleInfo:
    lines = source.count(b"\n") + (1 if source and not source.endswith(b"\n") else 0)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(source, filename=filename)
    except SyntaxError as e:
        return ModuleInfo(lines=lines, error=f"syntax error: {e.msg}", error_line=e.lineno)
    except (ValueError, RecursionError) as e:
        return ModuleInfo(lines=lines, error=f"cannot parse: {e}")

    extractor = _Extractor()
    extractor.run(tree)
    info = extractor.info
    info.lines = lines
    info.loc = _count_loc(source, extractor.doc_lines)
    return info


class _Extractor:
    def __init__(self) -> None:
        self.info = ModuleInfo()
        self.doc_lines: set[int] = set()

    def run(self, tree: ast.Module) -> None:
        self.info.doc = self._doc(tree)
        self._body(tree.body, _Ctx(), ())

    def _body(self, stmts: list[ast.stmt], ctx: _Ctx, scope: tuple[str, ...]) -> None:
        for stmt in stmts:
            self._stmt(stmt, ctx, scope)

    def _stmt(self, stmt: ast.stmt, ctx: _Ctx, scope: tuple[str, ...]) -> None:
        module_level = not scope and not ctx.lazy
        match stmt:
            case ast.Import():
                for alias in stmt.names:
                    self._import(alias.name, 0, None, alias.asname, stmt, ctx, module_level)
            case ast.ImportFrom():
                if stmt.module == "__future__":
                    return
                names = [(a.name, a.asname) for a in stmt.names]
                self._import(stmt.module, stmt.level, names, None, stmt, ctx, module_level)
            case ast.ClassDef():
                if module_level:
                    self.info.defined.add(stmt.name)
                doc = self._doc(stmt)
                if not ctx.lazy:
                    self.info.symbols.append(
                        Symbol(
                            kind="class",
                            qualname=".".join((*scope, stmt.name)),
                            range=_range(stmt),
                            doc=doc,
                            decorators=_decorators(stmt),
                            bases=[p for b in stmt.bases if (p := _dotted(b))],
                        )
                    )
                self._body(stmt.body, ctx, (*scope, stmt.name))
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                if module_level:
                    self.info.defined.add(stmt.name)
                doc = self._doc(stmt)
                # Functions nested in functions are folded into their parent.
                if not ctx.lazy:
                    self.info.symbols.append(
                        Symbol(
                            kind="method" if scope else "function",
                            qualname=".".join((*scope, stmt.name)),
                            range=_range(stmt),
                            doc=doc,
                            decorators=_decorators(stmt),
                            is_async=isinstance(stmt, ast.AsyncFunctionDef),
                            complexity=_complexity(stmt),
                        )
                    )
                self._body(stmt.body, replace(ctx, lazy=True), (*scope, stmt.name))
            case ast.If():
                if _is_type_checking(stmt.test):
                    self._body(stmt.body, replace(ctx, type_only=True), scope)
                    self._body(stmt.orelse, replace(ctx, conditional=True), scope)
                else:
                    branch = replace(ctx, conditional=True)
                    self._body(stmt.body, branch, scope)
                    self._body(stmt.orelse, branch, scope)
            case ast.Try() | ast.TryStar():
                branch = replace(ctx, conditional=True)
                self._body(stmt.body, branch, scope)
                for handler in stmt.handlers:
                    self._body(handler.body, branch, scope)
                self._body(stmt.orelse, branch, scope)
                self._body(stmt.finalbody, ctx, scope)
            case ast.For() | ast.AsyncFor() | ast.While():
                branch = replace(ctx, conditional=True)
                self._body(stmt.body, branch, scope)
                self._body(stmt.orelse, branch, scope)
            case ast.With() | ast.AsyncWith():
                self._body(stmt.body, ctx, scope)
            case ast.Match():
                for case in stmt.cases:
                    self._body(case.body, replace(ctx, conditional=True), scope)
            case ast.Assign() | ast.AnnAssign():
                if module_level:
                    self._assign(stmt)

    def _import(
        self,
        module: str | None,
        level: int,
        names: list[tuple[str, str | None]] | None,
        alias: str | None,
        stmt: ast.stmt,
        ctx: _Ctx,
        module_level: bool,
    ) -> None:
        self.info.imports.append(
            RawImport(
                module=module,
                level=level,
                names=names,
                alias=alias,
                line=stmt.lineno,
                module_level=module_level,
                type_only=ctx.type_only,
                lazy=ctx.lazy,
                conditional=ctx.conditional,
            )
        )

    def _assign(self, stmt: ast.Assign | ast.AnnAssign) -> None:
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        for target in targets:
            elts = target.elts if isinstance(target, ast.Tuple | ast.List) else [target]
            for elt in elts:
                if isinstance(elt, ast.Name):
                    self.info.defined.add(elt.id)
                    if elt.id == "__all__" and stmt.value is not None:
                        self.info.all_names = _string_list(stmt.value)

    def _doc(
        self, node: ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
    ) -> str | None:
        body = node.body
        if not (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            return None
        first = body[0]
        self.doc_lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
        text = ast.get_docstring(node) or ""
        line = next((s.strip() for s in text.splitlines() if s.strip()), None)
        return line[:200] if line else None


def _range(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[int, int]:
    start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
    return start, node.end_lineno or node.lineno


def _decorators(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    return [ast.unparse(d)[:100] for d in node.decorator_list]


def _dotted(expr: ast.expr) -> list[str] | None:
    """`a.b.C` or `a.b.C[T]` -> ["a", "b", "C"]; anything else -> None."""
    if isinstance(expr, ast.Subscript):
        expr = expr.value
    parts: list[str] = []
    while isinstance(expr, ast.Attribute):
        parts.append(expr.attr)
        expr = expr.value
    if isinstance(expr, ast.Name):
        parts.append(expr.id)
        return parts[::-1]
    return None


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _string_list(expr: ast.expr) -> list[str] | None:
    if not isinstance(expr, ast.List | ast.Tuple):
        return None
    values = [e.value for e in expr.elts if isinstance(e, ast.Constant)]
    return values if all(isinstance(v, str) for v in values) else None


def _complexity(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """McCabe-style: 1 + branch points. Nested functions count toward their parent."""
    count = 1
    stack: list[ast.AST] = list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, _BRANCHES):
            count += 1
        if isinstance(node, ast.comprehension):
            count += len(node.ifs)
        elif isinstance(node, ast.BoolOp):
            count += len(node.values) - 1
        stack.extend(ast.iter_child_nodes(node))
    return count


def _count_loc(source: bytes, doc_lines: set[int]) -> int:
    """Lines holding code, excluding blank lines, comments and docstrings."""
    lines: set[int] = set()
    try:
        for tok in tokenize.tokenize(io.BytesIO(source).readline):
            if tok.type not in _NON_CODE_TOKENS:
                lines.update(range(tok.start[0], tok.end[0] + 1))
    except (tokenize.TokenError, SyntaxError):
        return sum(1 for line in source.splitlines() if line.strip())
    return len(lines - doc_lines)
