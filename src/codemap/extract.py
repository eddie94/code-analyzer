"""Per-file extraction with the standard `ast` module.

Nothing here looks at other files: imports are recorded as written and resolved
later by `codemap.resolve`.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
import warnings
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from codemap.scan import SourceFile

if TYPE_CHECKING:
    from codemap.cache import ExtractCache

PARALLEL_THRESHOLD = 64
# Bump when extraction output changes so cached results are discarded.
EXTRACT_VERSION = 7

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
_HTTP_DECORATORS = {
    "get", "post", "put", "delete", "patch", "head", "options",
    "websocket", "route", "api_route",
}  # fmt: skip
_TYPE_WRAPPERS = {"Optional", "Annotated", "Final", "ClassVar", "Required", "NotRequired"}
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
class Value:
    """What an assignment, parameter or annotation says about a variable's type."""

    call: list[str] | None = None  # x = Foo(...) or x = make(...): the callee
    ref: list[str] | None = None  # x = other or x = self.attr
    annotation: list[str] | None = None  # x: Foo


@dataclass
class Ctx:
    """A statement that encloses a call or exit: `if`, `else`, a loop, `except`, `with`, `case`."""

    kind: Literal["if", "else", "loop", "except", "with", "case"]
    text: str  # condition or header as written; for "else", the condition it negates


@dataclass
class Exit:
    kind: Literal["return", "raise"]
    line: int
    value: str  # what is returned or raised, as written ("" for a bare return)
    context: list[Ctx] = field(default_factory=list)
    # Variables the value reads (see CallSite.inputs).
    inputs: list[str] = field(default_factory=list)


@dataclass
class Section:
    """A step heading written as a comment, e.g. `# Step 2. Load data`."""

    line: int
    title: str


@dataclass
class CallSite:
    # Dotted parts. A call in the chain is marked "()": make().run() -> ["make", "()", "run"],
    # and super().m() -> ["super", "m"]. None when the callee is not a name chain.
    callee: list[str] | None
    text: str  # the callee as written, for display
    line: int
    awaited: bool = False
    col: int = 0
    # Up to three positional arguments: dotted names as written, string literals quoted.
    args: list[str] = field(default_factory=list)
    context: list[Ctx] = field(default_factory=list)  # outermost first
    # Index (in Symbol.calls) of the call this one is an argument of, e.g. asyncio.gather.
    within: int | None = None
    # Names the result is assigned to: `a, b = f()` -> ["a", "b"].
    assigns: list[str] = field(default_factory=list)
    # Variables of the function read by the arguments: parameters, locals and `self.x`
    # attributes, e.g. f(a.b, self.c.d, g(e)) -> ["a", "self.c", "e"].
    inputs: list[str] = field(default_factory=list)
    # The variable the method is called on: self.gen.run() -> "self.gen", x.run() -> "x".
    receiver: str | None = None


@dataclass
class EntryDecorator:
    kind: Literal["route", "startup", "command", "task", "main"]
    label: str
    # The object the decorator hangs off, e.g. ["app"] for @app.post(...).
    owner: list[str] | None = None


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
    # Functions: parameters, return annotation, calls and assignments in the body.
    params: dict[str, Value] = field(default_factory=dict)
    arguments: list[str] = field(default_factory=list)  # every parameter name
    returns: list[str] | None = None
    calls: list[CallSite] = field(default_factory=list)
    locals: dict[str, list[Value]] = field(default_factory=dict)
    # Assignments to names declared `global`.
    globals: dict[str, list[Value]] = field(default_factory=dict)
    # Methods: `self.x = ...`; classes: attributes declared in the class body.
    attrs: dict[str, list[Value]] = field(default_factory=dict)
    entries: list[EntryDecorator] = field(default_factory=list)
    # Imports inside the function body (they bind local names).
    imports: list[RawImport] = field(default_factory=list)
    exits: list[Exit] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    # Names read in the body (used to link functions that share module globals).
    reads: list[str] = field(default_factory=list)


@dataclass
class ModuleInfo:
    lines: int = 0
    loc: int = 0
    doc: str | None = None
    all_names: list[str] | None = None
    defined: set[str] = field(default_factory=set)  # names defined (not imported) at module level
    imports: list[RawImport] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    # Module-level variable assignments.
    variables: dict[str, list[Value]] = field(default_factory=dict)
    error: str | None = None
    error_line: int | None = None


@dataclass(frozen=True)
class _Ctx:
    type_only: bool = False
    lazy: bool = False  # inside a function body
    conditional: bool = False


def extract_all(
    root: Path,
    files: list[SourceFile],
    jobs: int | None = None,
    cache: ExtractCache | None = None,
) -> list[ModuleInfo]:
    if cache is None:
        return _parse_all([root / f.path for f in files], jobs)

    results: list[ModuleInfo | None] = [None] * len(files)
    misses: list[tuple[int, str | None]] = []
    for i, f in enumerate(files):
        try:
            digest = cache.digest((root / f.path).read_bytes())
        except OSError:
            misses.append((i, None))
            continue
        results[i] = cache.get(f.path, digest)
        if results[i] is None:
            misses.append((i, digest))

    parsed = _parse_all([root / files[i].path for i, _ in misses], jobs)
    for (i, digest), info in zip(misses, parsed, strict=True):
        results[i] = info
        if digest is not None:
            cache.put(files[i].path, digest, info)
    cache.save()
    return results  # type: ignore[return-value]


def _parse_all(paths: list[Path], jobs: int | None) -> list[ModuleInfo]:
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
    comments: dict[int, str] = {}
    info.loc = _count_loc(source, extractor.doc_lines, comments)
    _assign_sections(info.symbols, _sections(comments))
    return info


class _Extractor:
    def __init__(self) -> None:
        self.info = ModuleInfo()
        self.doc_lines: set[int] = set()
        self.classes: dict[str, Symbol] = {}

    def run(self, tree: ast.Module) -> None:
        self.info.doc = self._doc(tree)
        self._body(tree.body, _Ctx(), ())
        self._module_code(tree)

    def _module_code(self, tree: ast.Module) -> None:
        """Statements that run on import, as a `__module__` pseudo-function.

        This is where frameworks get wired up: `app = FastAPI()`,
        `app.include_router(router)`, module-level clients and so on.
        """
        body = [
            stmt
            for stmt in tree.body
            if not isinstance(
                stmt,
                ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Import | ast.ImportFrom,
            )
            and not (isinstance(stmt, ast.If) and _is_main_check(stmt.test))
        ]
        symbol = Symbol(kind="function", qualname="__module__", range=(1, 1))
        _BodyScanner(symbol).scan(body)
        if symbol.calls:
            symbol.range = (body[0].lineno, body[-1].end_lineno or body[-1].lineno)
            self.info.symbols.append(symbol)

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
                    symbol = Symbol(
                        kind="class",
                        qualname=".".join((*scope, stmt.name)),
                        range=_range(stmt),
                        doc=doc,
                        decorators=_decorators(stmt),
                        bases=[p for b in stmt.bases if (p := _dotted(b))],
                    )
                    self.classes[symbol.qualname] = symbol
                    self.info.symbols.append(symbol)
                self._body(stmt.body, ctx, (*scope, stmt.name))
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                if module_level:
                    self.info.defined.add(stmt.name)
                doc = self._doc(stmt)
                # Functions nested in functions are folded into their parent.
                if not ctx.lazy:
                    symbol = Symbol(
                        kind="method" if scope else "function",
                        qualname=".".join((*scope, stmt.name)),
                        range=_range(stmt),
                        doc=doc,
                        decorators=_decorators(stmt),
                        is_async=isinstance(stmt, ast.AsyncFunctionDef),
                        complexity=_complexity(stmt),
                        params=_params(stmt.args),
                        arguments=_argument_names(stmt.args),
                        returns=_annotation(stmt.returns),
                        entries=_entries(stmt),
                    )
                    _BodyScanner(symbol).scan(stmt.body)
                    self.info.symbols.append(symbol)
                self._body(stmt.body, replace(ctx, lazy=True), (*scope, stmt.name))
            case ast.If():
                if module_level and _is_main_check(stmt.test):
                    # `if __name__ == "__main__":` runs like a function when executed as a script.
                    main = Symbol(
                        kind="function",
                        qualname="__main__",
                        range=(stmt.lineno, stmt.end_lineno or stmt.lineno),
                        entries=[EntryDecorator("main", "__main__")],
                    )
                    _BodyScanner(main).scan(stmt.body)
                    self.info.symbols.append(main)
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
                    _record_assignment(stmt, self.info.variables)
                elif not ctx.lazy and ".".join(scope) in self.classes:
                    _record_assignment(stmt, self.classes[".".join(scope)].attrs)

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


class _BodyScanner(ast.NodeVisitor):
    """Collect calls, exits and assignments in a function body, with their context.

    Nested functions are folded into the body: their calls count as this function's.
    """

    def __init__(self, symbol: Symbol) -> None:
        self.symbol = symbol
        self.awaited: set[int] = set()
        self.global_names: set[str] = set()
        self.context: list[Ctx] = []
        self.argument_of: int | None = None
        self.reads: set[str] = set()
        self.results: dict[int, list[str]] = {}  # id(call node) -> names its result goes to
        self.stored: set[str] = set()

    def scan(self, body: list[ast.stmt]) -> None:
        for stmt in body:
            self.visit(stmt)
        self.symbol.reads = sorted(self.reads)
        # Only now are all local names known: keep the inputs that are this function's variables.
        own = (self.stored | set(self.symbol.arguments)) - {"self", "cls"}

        def is_own(name: str | None) -> bool:
            return name is not None and (name.startswith("self.") or name in own)

        for call in self.symbol.calls:
            call.inputs = [n for n in call.inputs if is_own(n)]
            call.receiver = call.receiver if is_own(call.receiver) else None
        for exit in self.symbol.exits:
            exit.inputs = [n for n in exit.inputs if is_own(n)]

    def _inside(self, ctx: Ctx, body: list[ast.stmt]) -> None:
        self.context.append(ctx)
        for stmt in body:
            self.visit(stmt)
        self.context.pop()

    # ---------- control flow ----------

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        text = _source(node.test)
        self._inside(Ctx("if", text), node.body)
        if node.orelse:
            self._inside(Ctx("else", text), node.orelse)

    def visit_For(self, node: ast.For | ast.AsyncFor) -> None:
        self.visit(node.iter)
        self.visit(node.target)
        self._inside(Ctx("loop", f"for {_source(node.target)} in {_source(node.iter)}"), node.body)
        for stmt in node.orelse:
            self.visit(stmt)

    visit_AsyncFor = visit_For

    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)
        self._inside(Ctx("loop", f"while {_source(node.test)}"), node.body)
        for stmt in node.orelse:
            self.visit(stmt)

    def visit_Try(self, node: ast.Try | ast.TryStar) -> None:
        for stmt in [*node.body, *node.orelse]:
            self.visit(stmt)
        for handler in node.handlers:
            caught = f"except {_source(handler.type)}" if handler.type else "except"
            self._inside(Ctx("except", caught), handler.body)
        for stmt in node.finalbody:
            self.visit(stmt)

    visit_TryStar = visit_Try

    def visit_With(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item)
        managers = [i.context_expr for i in node.items if isinstance(i.context_expr, ast.Call)]
        if managers:
            prefix = "async with" if isinstance(node, ast.AsyncWith) else "with"
            self._inside(Ctx("with", f"{prefix} {', '.join(map(_source, managers))}"), node.body)
        else:
            for stmt in node.body:
                self.visit(stmt)

    visit_AsyncWith = visit_With

    def visit_Match(self, node: ast.Match) -> None:
        self.visit(node.subject)
        for case in node.cases:
            text = _source(case.pattern) + (f" if {_source(case.guard)}" if case.guard else "")
            self._inside(Ctx("case", text), case.body)

    def visit_Return(self, node: ast.Return) -> None:
        self._exit("return", node, node.value)

    def visit_Raise(self, node: ast.Raise) -> None:
        self._exit("raise", node, node.exc)

    def _exit(
        self, kind: Literal["return", "raise"], node: ast.stmt, value: ast.expr | None
    ) -> None:
        self.symbol.exits.append(
            Exit(
                kind,
                node.lineno,
                _source(value) if value else "",
                list(self.context),
                _variables_read([value] if value else []),
            )
        )
        self.generic_visit(node)

    # ---------- calls and names ----------

    def visit_Await(self, node: ast.Await) -> None:
        if isinstance(node.value, ast.Call):
            self.awaited.add(id(node.value))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        index = len(self.symbol.calls)
        self.symbol.calls.append(
            CallSite(
                callee=_callee(node.func),
                text=ast.unparse(node.func)[:80],
                line=node.lineno,
                awaited=id(node) in self.awaited,
                col=node.col_offset,
                args=[a for a in map(_argument, node.args[:3]) if a],
                context=list(self.context),
                within=self.argument_of,
                assigns=self.results.get(id(node), []),
                inputs=_variables_read([*node.args, *(k.value for k in node.keywords)]),
                receiver=_receiver(node.func),
            )
        )
        self.visit(node.func)
        outer, self.argument_of = self.argument_of, index
        for arg in node.args:
            self.visit(arg)
        for keyword in node.keywords:
            self.visit(keyword.value)
        self.argument_of = outer

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.reads.add(node.id)
        else:
            self.stored.add(node.id)

    def visit_Global(self, node: ast.Global) -> None:
        self.global_names.update(node.names)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.symbol.imports.append(_local_import(alias.name, 0, None, alias.asname, node))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        names = [(a.name, a.asname) for a in node.names]
        self.symbol.imports.append(_local_import(node.module, node.level, names, None, node))

    # ---------- assignments ----------

    def visit_Assign(self, node: ast.Assign) -> None:
        self._assign(node)
        self._note_result(node.targets, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._assign(node)
        self._note_result([node.target], node.value)
        self.generic_visit(node)

    def _note_result(self, targets: list[ast.expr], value: ast.expr | None) -> None:
        if isinstance(value, ast.Await):
            value = value.value
        if not isinstance(value, ast.Call):
            return
        names = [
            n.id
            for t in targets
            for n in (t.elts if isinstance(t, ast.Tuple | ast.List) else [t])
            if isinstance(n, ast.Name)
        ]
        if names:
            self.results[id(value)] = names

    def visit_withitem(self, node: ast.withitem) -> None:
        if isinstance(node.optional_vars, ast.Name) and (value := _value(node.context_expr)):
            self.symbol.locals.setdefault(node.optional_vars.id, []).append(value)
        self.generic_visit(node)

    def _assign(self, node: ast.Assign | ast.AnnAssign) -> None:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        annotation = node.annotation if isinstance(node, ast.AnnAssign) else None
        value = _value(node.value, annotation)
        if value is None:
            return
        for target in targets:
            if isinstance(target, ast.Name):
                scope = (
                    self.symbol.globals if target.id in self.global_names else self.symbol.locals
                )
                scope.setdefault(target.id, []).append(value)
            elif (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                self.symbol.attrs.setdefault(target.attr, []).append(value)


def _source(expr: ast.AST, limit: int = 100) -> str:
    text = " ".join(ast.unparse(expr).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _argument(expr: ast.expr) -> str | None:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return f'"{expr.value[:100]}"'
    chain = _name_chain(expr)
    return ".".join(chain) if chain else None


def _variable(chain: list[str]) -> str:
    """The variable a name chain reads: a.b.c -> "a", self.x.y -> "self.x"."""
    return ".".join(chain[:2]) if chain[0] == "self" and len(chain) > 1 else chain[0]


def _variables_read(exprs: list[ast.expr]) -> list[str]:
    """Variables read by the expressions, in order, without repeats (unfiltered)."""
    found: list[str] = []

    def walk(node: ast.AST, bound: frozenset[str]) -> None:
        if isinstance(node, ast.Name | ast.Attribute) and (chain := _name_chain(node)):
            if not isinstance(node, ast.Name) or isinstance(node.ctx, ast.Load):
                name = _variable(chain)
                if name not in found and chain[0] not in bound:
                    found.append(name)
            return
        if isinstance(node, ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp):
            # Loop variables of a comprehension are its own, not the function's.
            bound = bound | {
                n.id for g in node.generators for n in ast.walk(g.target) if isinstance(n, ast.Name)
            }
        elif isinstance(node, ast.Lambda):
            bound = bound | {a.arg for a in node.args.args}
        elif isinstance(node, ast.Call):
            # A call reads the object it is made on, not the method: f(self.g(x)) reads self, x.
            func = node.func.value if isinstance(node.func, ast.Attribute) else None
            for child in [func, *node.args, *(k.value for k in node.keywords)]:
                if child is not None:
                    walk(child, bound)
            return
        for child in ast.iter_child_nodes(node):
            walk(child, bound)

    for expr in exprs:
        walk(expr, frozenset())
    return found


def _receiver(func: ast.expr) -> str | None:
    """The variable a method is called on; None for plain functions and `self.method()`."""
    if not isinstance(func, ast.Attribute):
        return None
    chain = _name_chain(func.value)
    if not chain or chain == ["self"]:
        return None
    return _variable(chain)


def _local_import(
    module: str | None,
    level: int,
    names: list[tuple[str, str | None]] | None,
    alias: str | None,
    node: ast.stmt,
) -> RawImport:
    return RawImport(module, level, names, alias, node.lineno, False, False, True, False)


def _record_assignment(stmt: ast.Assign | ast.AnnAssign, into: dict[str, list[Value]]) -> None:
    targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
    annotation = stmt.annotation if isinstance(stmt, ast.AnnAssign) else None
    value = _value(stmt.value, annotation)
    if value is None:
        return
    for target in targets:
        if isinstance(target, ast.Name):
            into.setdefault(target.id, []).append(value)


def _value(expr: ast.expr | None, annotation: ast.expr | None = None) -> Value | None:
    if isinstance(expr, ast.Await):
        expr = expr.value
    value = Value(
        call=_callee(expr.func) if isinstance(expr, ast.Call) else None,
        ref=_name_chain(expr) if isinstance(expr, ast.Name | ast.Attribute) else None,
        annotation=_annotation(annotation),
    )
    return value if value.call or value.ref or value.annotation else None


def _argument_names(args: ast.arguments) -> list[str]:
    names = [a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]]
    names += [a.arg for a in (args.vararg, args.kwarg) if a]
    return names


def _params(args: ast.arguments) -> dict[str, Value]:
    positional = [*args.posonlyargs, *args.args]
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(args.defaults))
    defaults += args.defaults
    pairs = [
        *zip(positional, defaults, strict=True),
        *zip(args.kwonlyargs, args.kw_defaults, strict=True),
    ]
    params = {}
    for arg, default in pairs:
        if value := _value(default, arg.annotation):
            params[arg.arg] = value
    return params


def _name_chain(expr: ast.expr) -> list[str] | None:
    """`a.b.c` -> ["a", "b", "c"]; anything else -> None."""
    parts: list[str] = []
    while isinstance(expr, ast.Attribute):
        parts.append(expr.attr)
        expr = expr.value
    if isinstance(expr, ast.Name):
        parts.append(expr.id)
        return parts[::-1]
    return None


def _callee(func: ast.expr) -> list[str] | None:
    if isinstance(func, ast.Subscript):  # Generic[T](...)
        func = func.value
    attrs: list[str] = []
    node = func
    while isinstance(node, ast.Attribute):
        attrs.append(node.attr)
        node = node.value
    attrs.reverse()
    if isinstance(node, ast.Name):
        return [node.id, *attrs]
    if isinstance(node, ast.Call) and attrs:
        if isinstance(node.func, ast.Name) and node.func.id == "super":
            return ["super", *attrs] if len(attrs) == 1 else None
        inner = _callee(node.func)
        return [*inner, "()", *attrs] if inner else None
    return None


def _annotation(expr: ast.expr | None) -> list[str] | None:
    """The class an annotation names: `Foo`, `Optional[Foo]`, `Foo | None`, `"Foo"`."""
    if expr is None:
        return None
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        try:
            return _annotation(ast.parse(expr.value, mode="eval").body)
        except SyntaxError:
            return None
    if isinstance(expr, ast.Subscript):
        base = _name_chain(expr.value)
        if base and base[-1] in _TYPE_WRAPPERS:
            inner = expr.slice.elts[0] if isinstance(expr.slice, ast.Tuple) else expr.slice
            return _annotation(inner)
        return None
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.BitOr):
        sides = [expr.left, expr.right]
        named = [s for s in sides if not (isinstance(s, ast.Constant) and s.value is None)]
        return _annotation(named[0]) if len(named) == 1 else None
    return _name_chain(expr)


def _entries(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[EntryDecorator]:
    """Decorators that make a function an entry point: routes, startup hooks, commands, tasks."""
    entries = []
    for decorator in fn.decorator_list:
        call = decorator if isinstance(decorator, ast.Call) else None
        func = call.func if call else decorator
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        first = (
            call.args[0].value
            if call and call.args and isinstance(call.args[0], ast.Constant)
            else None
        )
        keywords = {k.arg: k.value for k in call.keywords} if call else {}
        owner = _name_chain(func.value) if isinstance(func, ast.Attribute) else None
        if name in _HTTP_DECORATORS and isinstance(func, ast.Attribute) and isinstance(first, str):
            if name in ("route", "api_route"):
                methods = _string_list(keywords["methods"]) if "methods" in keywords else None
                method = "/".join(methods or ["GET"])
            else:
                method = "WS" if name == "websocket" else name.upper()
            entries.append(EntryDecorator("route", f"{method} {first}", owner))
        elif name == "on_event" and first in ("startup", "shutdown"):
            entries.append(EntryDecorator("startup", f"on {first}", owner))
        elif name == "command":
            label = first if isinstance(first, str) else fn.name.replace("_", "-")
            entries.append(EntryDecorator("command", label, owner))
        elif name in ("task", "shared_task"):
            entries.append(EntryDecorator("task", fn.name, owner))
    return entries


def _is_main_check(test: ast.expr) -> bool:
    if not (
        isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq)
    ):
        return False
    sides = [test.left, test.comparators[0]]
    names = [s.id for s in sides if isinstance(s, ast.Name)]
    values = [s.value for s in sides if isinstance(s, ast.Constant)]
    return names == ["__name__"] and values == ["__main__"]


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


def _count_loc(source: bytes, doc_lines: set[int], comments: dict[int, str]) -> int:
    """Lines holding code, excluding blank lines, comments and docstrings.

    Comments are collected into `comments` (line -> text) along the way.
    """
    lines: set[int] = set()
    try:
        # The 3.12 tokenizer reports invalid escapes as SyntaxWarning, like ast.parse.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for tok in tokenize.tokenize(io.BytesIO(source).readline):
                if tok.type == tokenize.COMMENT:
                    comments[tok.start[0]] = tok.string
                elif tok.type not in _NON_CODE_TOKENS:
                    lines.update(range(tok.start[0], tok.end[0] + 1))
    except (tokenize.TokenError, SyntaxError):
        return sum(1 for line in source.splitlines() if line.strip())
    return len(lines - doc_lines)


_INLINE_HEADING = re.compile(r"^#{3,}\s*\S.*\S\s*#{3,}$|^#\s*[-=]{3,}\s*\S.*\S\s*[-=]{3,}$")
_STEP_COMMENT = re.compile(r"^(step|stage|phase)\s*\d+|^\d+[.)]\s", re.IGNORECASE)


def _sections(comments: dict[int, str]) -> list[Section]:
    """Step headings: a comment between two `####` lines, `### Title ###` / `# --- Title ---`,
    or one starting with "Step 1", "1." and the like."""

    def banner(line: int) -> bool:
        text = comments.get(line, "")
        return len(text) >= 4 and set(text.strip()) <= {"#", "-", "=", "*"}

    sections = []
    for line, text in sorted(comments.items()):
        title = text.strip().strip("#-=* \u3000").strip()
        framed = banner(line - 1) and banner(line + 1)
        inline = _INLINE_HEADING.match(text.strip()) is not None
        if title and (framed or inline or _STEP_COMMENT.match(title)):
            sections.append(Section(line, title[:80]))
    return sections


def _assign_sections(symbols: list[Symbol], sections: list[Section]) -> None:
    """Give each heading to the innermost function whose body contains it."""
    functions = [s for s in symbols if s.kind != "class"]
    for section in sections:
        owners = [f for f in functions if f.range[0] < section.line <= f.range[1]]
        if owners:
            min(owners, key=lambda f: f.range[1] - f.range[0]).sections.append(section)
