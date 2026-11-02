"""Static call graph: resolve call sites to functions and methods (best effort).

Receivers are typed from what the code states: annotations, `x = Cls(...)`,
`self.x = ...` in any method, module globals (including `global` assignments),
parameter defaults, and return annotations. Calls that cannot be followed are
kept as text on the calling function rather than guessed.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Literal

from codemap.extract import ModuleInfo, Symbol, Value
from codemap.model import Edge, EntryPoint, Flow, FlowContext, FlowExit, FlowSection, FlowStep
from codemap.resolve import Ref, Resolver
from codemap.scan import SourceFile

Confidence = Literal["exact", "inferred", "candidates"]
_RANK: dict[str, int] = {"exact": 0, "inferred": 1, "candidates": 2}
_PREFIX = {"class": "cls", "function": "fn", "method": "meth"}
_MAX_DEPTH = 12
MAX_UNRESOLVED = 30
ENTRY_ORDER = ["route", "startup", "main", "command", "script", "task"]
# Calls that run their coroutine arguments concurrently, or in the background.
_PARALLEL = {"gather", "wait", "as_completed"}
_BACKGROUND = {
    "create_task",
    "ensure_future",
    "start_soon",
    "add_task",
    "submit",
    "run_in_executor",
}
# Methods of builtin data types and loggers. Calls to these on untyped values are
# almost never the missing link in a flow, so they are not listed as unresolved.
_DATA_METHODS = {
    "append", "extend", "insert", "remove", "pop", "clear", "copy", "sort", "reverse", "count",
    "index", "get", "items", "keys", "values", "update", "setdefault", "add", "discard",
    "join", "split", "rsplit", "splitlines", "strip", "lstrip", "rstrip", "startswith",
    "endswith", "replace", "format", "lower", "upper", "title", "find", "rfind", "encode",
    "decode", "isdigit", "isalpha", "zfill", "match", "search", "sub", "findall", "finditer",
    "fullmatch", "group", "groups", "debug", "info", "warning", "warn", "error", "exception",
    "critical", "log", "isoformat", "strftime", "total_seconds", "read", "write", "close",
}  # fmt: skip


@dataclass
class Func:
    id: str
    qualname: str
    module: str
    symbol: Symbol
    cls: str | None  # owning class qualname, for methods


@dataclass
class Klass:
    qualname: str
    module: str
    symbol: Symbol
    methods: dict[str, Func] = field(default_factory=dict)
    bases: list[str] = field(default_factory=list)
    subclasses: list[str] = field(default_factory=list)
    # attribute -> values, with the method whose body assigned them (None: class body)
    attrs: dict[str, list[tuple[Value, Func | None]]] = field(default_factory=dict)


@dataclass
class Call:
    targets: list[tuple[str, Confidence]] = field(default_factory=list)  # node ids
    library: str | None = None  # dotted name, e.g. "requests.post"
    builtin: bool = False


@dataclass
class CallGraphResult:
    edges: list[Edge]
    unresolved: dict[str, list[str]]  # function node id -> calls as written
    entrypoints: list[EntryPoint]
    flows: dict[str, Flow]  # function node id -> flow


@dataclass
class _EdgeAcc:
    line: int
    awaited: bool = False
    confidence: Confidence = "candidates"
    names: set[str] = field(default_factory=set)


class CallGraph:
    def __init__(self, resolver: Resolver) -> None:
        self.resolver = resolver
        self.funcs: dict[str, Func] = {}
        self.classes: dict[str, Klass] = {}
        # module -> variable -> values, with the function that assigned them (None: top level)
        self.module_vars: dict[str, dict[str, list[tuple[Value, Func | None]]]] = {}
        self._types: dict[tuple, set[str]] = {}
        self._local_bindings: dict[str, dict] = {}
        self._spawner_ids: set[str] | None = None
        self._index(resolver.modules)

    # ---------- indexing ----------

    def _index(self, modules: dict[str, tuple[SourceFile, ModuleInfo]]) -> None:
        for module, (_, info) in modules.items():
            variables = self.module_vars.setdefault(module, {})
            for name, values in info.variables.items():
                variables.setdefault(name, []).extend((v, None) for v in values)
            for sym in info.symbols:
                qualname = f"{module}.{sym.qualname}"
                if sym.kind == "class":
                    self.classes[qualname] = Klass(qualname, module, sym)
                    continue
                owner = sym.qualname.rpartition(".")[0]
                func = Func(
                    f"{_PREFIX[sym.kind]}:{qualname}",
                    qualname,
                    module,
                    sym,
                    f"{module}.{owner}" if owner else None,
                )
                self.funcs[func.id] = func

        for klass in self.classes.values():
            for name, values in klass.symbol.attrs.items():
                klass.attrs.setdefault(name, []).extend((v, None) for v in values)
            for base in klass.symbol.bases:
                resolved = self.resolver.resolve_class(klass.module, base)
                if resolved in self.classes:
                    klass.bases.append(resolved)
                    self.classes[resolved].subclasses.append(klass.qualname)

        for func in self.funcs.values():
            if func.cls in self.classes:
                klass = self.classes[func.cls]
                klass.methods[func.symbol.qualname.rpartition(".")[2]] = func
                for name, values in func.symbol.attrs.items():
                    klass.attrs.setdefault(name, []).extend((v, func) for v in values)
            variables = self.module_vars[func.module]
            for name, values in func.symbol.globals.items():
                variables.setdefault(name, []).extend((v, func) for v in values)

    # ---------- building ----------

    def build(self) -> CallGraphResult:
        edges: dict[tuple[str, str], _EdgeAcc] = {}
        unresolved: dict[str, list[str]] = {}
        flows: dict[str, Flow] = {}
        for func in self.funcs.values():
            missing: list[str] = []
            resolved = [
                self.resolve_call(site.callee, func.module, func) for site in func.symbol.calls
            ]
            if flow := self._flow(func, resolved):
                flows[func.id] = flow
            for site, call in zip(func.symbol.calls, resolved, strict=True):
                targets = list(call.targets)
                if call.library:
                    targets.append((_library_node(call.library), "exact"))
                if not targets:
                    # Only name chains are listed: other callees are expressions on data.
                    if (
                        site.callee
                        and not call.builtin
                        and site.text not in missing
                        and not _is_data_call(site.callee)
                    ):
                        missing.append(site.text)
                    continue
                for target, confidence in targets:
                    acc = edges.setdefault((func.id, target), _EdgeAcc(site.line))
                    acc.line = min(acc.line, site.line)
                    acc.awaited |= site.awaited
                    if _RANK[confidence] < _RANK[acc.confidence]:
                        acc.confidence = confidence
                    if call.library and target.startswith(("stdlib:", "external:")):
                        acc.names.add(call.library)
            if missing:
                unresolved[func.id] = missing[:MAX_UNRESOLVED]

        result = [
            Edge(
                source=source,
                target=target,
                kind="calls",
                line=acc.line,
                names=sorted(acc.names),
                awaited=acc.awaited,
                confidence=acc.confidence,
            )
            for (source, target), acc in edges.items()
        ]
        return CallGraphResult(result, unresolved, self._entrypoints(), flows)

    def _flow(self, func: Func, resolved: list[Call]) -> Flow | None:
        sites = func.symbol.calls
        steps = []
        for site, call in zip(sites, resolved, strict=True):
            followed = call.targets or call.library
            if not followed and (not site.callee or call.builtin or _is_data_call(site.callee)):
                continue
            group, background = None, False
            if site.within is not None:
                outer, outer_call = sites[site.within], resolved[site.within]
                name = _last_name(outer_call.library or ".".join(outer.callee or []))
                if name in _PARALLEL:
                    group = outer.line
                elif name in _BACKGROUND or any(
                    t in self._spawners() for t, _ in outer_call.targets
                ):
                    background = True
            confidences = {c for _, c in call.targets}
            confidence = min(confidences, key=_RANK.__getitem__) if confidences else None
            steps.append(
                FlowStep(
                    line=site.line,
                    col=site.col,
                    text=site.text,
                    targets=[t for t, _ in call.targets],
                    library=call.library,
                    confidence=confidence,
                    awaited=site.awaited,
                    context=[FlowContext(kind=c.kind, text=c.text) for c in site.context],
                    group=group,
                    background=background,
                    assigns=site.assigns,
                    inputs=site.inputs,
                    receiver=site.receiver,
                    nested=site.within is not None and group is None and not background,
                )
            )
        exits = [
            FlowExit(
                kind=e.kind,
                line=e.line,
                value=e.value,
                context=[FlowContext(kind=c.kind, text=c.text) for c in e.context],
                inputs=e.inputs,
            )
            for e in func.symbol.exits
        ]
        sections = [FlowSection(line=x.line, title=x.title) for x in func.symbol.sections]
        if not (steps or exits or sections):
            return None
        steps.sort(key=lambda x: (x.line, x.col))
        params = [a for a in func.symbol.arguments if a not in ("self", "cls")]
        return Flow(params=params, steps=steps, exits=exits, sections=sections)

    def _spawners(self) -> set[str]:
        """Functions that hand one of their parameters to create_task (or similar)."""
        if self._spawner_ids is None:
            self._spawner_ids = {
                func.id
                for func in self.funcs.values()
                for site in func.symbol.calls
                if site.callee
                and site.callee[-1] in _BACKGROUND
                and set(site.args) & set(func.symbol.arguments)
            }
        return self._spawner_ids

    def _entrypoints(self) -> list[EntryPoint]:
        entries = []
        for func in self.funcs.values():
            for entry in func.symbol.entries:
                label = entry.label
                if entry.kind == "main":
                    label = f"python {self.resolver.modules[func.module][0].path}"
                entries.append(EntryPoint(kind=entry.kind, label=label, target=func.id))
        return entries

    # ---------- call resolution ----------

    def resolve_call(self, parts: list[str] | None, module: str, func: Func | None) -> Call:
        if not parts:
            return Call()
        if "()" in parts:
            return self._call_on_result(parts, module, func)
        head = parts[0]
        if head == "super" and len(parts) == 2 and func and func.cls in self.classes:
            for base in self._mro(func.cls)[1:]:
                if method := self.classes[base].methods.get(parts[1]):
                    return Call([(method.id, "exact")])
            return Call()

        if self._is_local(head, func):
            if len(parts) == 1:
                return Call()  # calling a local callable object
            receivers = self.types_of(parts[:-1], module, func)
            exact = head == "self" and len(parts) == 2
            call = self._methods(receivers, parts[-1], "exact" if exact else "inferred")
            if not call.targets and (library := self._library_of(parts[:-1], module, func)):
                call.library = ".".join([library, *parts[len(parts) - 1 :]])
            return call

        ref = self._ref(parts, module, func)
        return self._call_ref(ref, module, func) if ref else Call()

    def _ref(self, parts: list[str], module: str, func: Func | None) -> Ref | None:
        """Resolve a name, preferring imports made inside the function."""
        if func and func.symbol.imports:
            bindings = self._local_bindings.get(func.id)
            if bindings is None:
                sf = self.resolver.modules[func.module][0]
                bindings = self._local_bindings[func.id] = self.resolver.bind(
                    sf, func.symbol.imports
                )
            if parts[0] in bindings:
                return self.resolver.resolve_binding(bindings[parts[0]], parts[1:])
        return self.resolver.resolve_ref(module, parts)

    def _call_on_result(self, parts: list[str], module: str, func: Func | None) -> Call:
        """`make().run()`: type the inner call's result, then look up the method on it."""
        split = len(parts) - 1 - parts[::-1].index("()")
        inner, attrs = parts[:split], parts[split + 1 :]
        receivers = self._walk(self._value_types(Value(call=inner), module, func, 0), attrs[:-1])
        call = self._methods(receivers, attrs[-1], "inferred")
        if not call.targets and "()" not in inner:
            ref = self._ref(inner, module, func)
            if ref and ref.kind == "lib":
                library = ".".join([ref.name, *ref.rest])
                if _is_class_name(library.rpartition(".")[2]):
                    call.library = ".".join([library, *attrs])
        return call

    def _call_ref(self, ref: Ref, module: str, func: Func | None) -> Call:
        if ref.kind == "builtin":
            return Call(builtin=True)
        if ref.kind == "lib":
            return Call(library=".".join([ref.name, *ref.rest]))
        if ref.kind == "function" and not ref.rest:
            return Call([(f"fn:{ref.name}", "exact")])
        if ref.kind == "class":
            qualname, rest = self._nested_class(ref.name, ref.rest)
            if not rest:
                init = self._method(qualname, "__init__")
                return Call([(init.id if init else f"cls:{qualname}", "exact")])
            if len(rest) == 1:
                method = self._method(qualname, rest[0])
                return Call([(method.id, "exact")] if method else [])
        if ref.kind == "var" and ref.rest:
            var_module, _, name = ref.name.rpartition(".")
            receivers = self._walk(self._var_types(var_module, name), ref.rest[:-1])
            return self._methods(receivers, ref.rest[-1], "inferred")
        return Call()

    def _methods(self, receivers: set[str], name: str, confidence: Confidence) -> Call:
        found: dict[str, Confidence] = {}
        for receiver in sorted(receivers):
            method = self._method(receiver, name)
            if method:
                found.setdefault(method.id, confidence)
                # A call through a base class may land in any override.
                for sub in self._subclasses(receiver):
                    if override := self.classes[sub].methods.get(name):
                        found.setdefault(override.id, "candidates")
        if len(found) > 1:
            found = {target: "candidates" for target in found}
        return Call(sorted(found.items()))

    # ---------- types ----------

    def types_of(
        self, parts: list[str], module: str, func: Func | None, depth: int = 0
    ) -> set[str]:
        """Classes that the value named by `parts` may be an instance of."""
        key = (module, func.id if func else None, tuple(parts))
        if key in self._types:
            return self._types[key]
        if depth > _MAX_DEPTH:
            return set()
        self._types[key] = set()  # breaks cycles such as `x = x.child`
        head, rest = parts[0], parts[1:]
        if head == "self" and func and func.cls in self.classes:
            base = {func.cls}
        elif self._is_local(head, func):
            assert func is not None
            values = list(func.symbol.locals.get(head, []))
            if head in func.symbol.params:
                values.append(func.symbol.params[head])
            base = self._union(values, module, func, depth)
        else:
            ref = self._ref(parts, module, func)
            if ref is None or ref.kind != "var":
                base = set()
            else:
                var_module, _, name = ref.name.rpartition(".")
                base, rest = self._var_types(var_module, name, depth), ref.rest
        result = self._walk(base, rest, depth)
        self._types[key] = result
        return result

    def _walk(self, classes: set[str], attrs: list[str], depth: int = 0) -> set[str]:
        for attr in attrs:
            classes = {t for c in classes for t in self._attr_types(c, attr, depth)}
        return classes

    def _attr_types(self, cls: str, attr: str, depth: int) -> set[str]:
        key = ("attr", cls, attr)
        if key in self._types:
            return self._types[key]
        self._types[key] = set()  # breaks cycles such as `self.a = self.b`, `self.b = self.a`
        result: set[str] = set()
        for klass_name in self._mro(cls):
            klass = self.classes[klass_name]
            for value, owner in klass.attrs.get(attr, []):
                result |= self._value_types(
                    value, owner.module if owner else klass.module, owner, depth
                )
            method = klass.methods.get(attr)
            if method and "property" in method.symbol.decorators and method.symbol.returns:
                result |= self._classes_named(method.module, method.symbol.returns)
            if result:
                break
        self._types[key] = result
        return result

    def _var_types(self, module: str, name: str, depth: int = 0) -> set[str]:
        key = ("var", module, name)
        if key in self._types:
            return self._types[key]
        self._types[key] = set()  # breaks cycles such as `x = x.copy()`
        values = self.module_vars.get(module, {}).get(name, [])
        result = {
            t
            for value, owner in values
            for t in self._value_types(value, owner.module if owner else module, owner, depth)
        }
        self._types[key] = result
        return result

    def _union(self, values: list[Value], module: str, func: Func | None, depth: int) -> set[str]:
        return {t for v in values for t in self._value_types(v, module, func, depth)}

    def _value_types(self, value: Value, module: str, func: Func | None, depth: int) -> set[str]:
        result: set[str] = set()
        if value.annotation:
            result |= self._classes_named(module, value.annotation)
        if value.call:
            for target, _ in self.resolve_call(value.call, module, func).targets:
                kind, _, qualname = target.partition(":")
                if kind == "cls":
                    result.add(qualname)
                elif target.endswith(".__init__"):
                    result.add(qualname.rpartition(".")[0])
                elif (callee := self.funcs.get(target)) and callee.symbol.returns:
                    result |= self._classes_named(callee.module, callee.symbol.returns)
        if value.ref:
            result |= self.types_of(value.ref, module, func, depth + 1)
        return result

    def _classes_named(self, module: str, parts: list[str]) -> set[str]:
        ref = self.resolver.resolve_ref(module, parts)
        if ref is None or ref.kind != "class":
            return set()
        qualname, rest = self._nested_class(ref.name, ref.rest)
        return {qualname} if not rest else set()

    def _library_of(self, parts: list[str], module: str, func: Func | None) -> str | None:
        """The library class of a local value, e.g. a session from aiohttp.ClientSession().

        Only class-like names count: the result of `json.loads(...)` is plain data, and a
        parameter default such as FastAPI's `Body(...)` says nothing about the value.
        """
        if len(parts) != 1 or func is None:
            return None
        named = [v.call for v in func.symbol.locals.get(parts[0], []) if v.call]
        named += [v.annotation for v in func.symbol.locals.get(parts[0], []) if v.annotation]
        if parts[0] in func.symbol.params and (
            annotation := func.symbol.params[parts[0]].annotation
        ):
            named.append(annotation)
        for name in named:
            ref = self._ref(name, module, func)
            if ref and ref.kind == "lib" and _is_class_name((ref.rest or ref.name.split("."))[-1]):
                return ".".join([ref.name, *ref.rest])
        return None

    # ---------- classes ----------

    def _nested_class(self, qualname: str, rest: list[str]) -> tuple[str, list[str]]:
        while rest and f"{qualname}.{rest[0]}" in self.classes:
            qualname, rest = f"{qualname}.{rest[0]}", rest[1:]
        return qualname, rest

    def _mro(self, cls: str) -> list[str]:
        order: list[str] = []
        stack = [cls]
        while stack:
            current = stack.pop(0)
            if current in order or current not in self.classes:
                continue
            order.append(current)
            stack.extend(self.classes[current].bases)
        return order

    def _method(self, cls: str, name: str) -> Func | None:
        for klass in self._mro(cls):
            if method := self.classes[klass].methods.get(name):
                return method
        return None

    def _subclasses(self, cls: str) -> list[str]:
        result: list[str] = []
        stack = list(self.classes[cls].subclasses) if cls in self.classes else []
        while stack:
            current = stack.pop()
            if current not in result:
                result.append(current)
                stack.extend(self.classes[current].subclasses)
        return result

    @staticmethod
    def _is_local(name: str, func: Func | None) -> bool:
        if func is None:
            return False
        return name == "self" or name in func.symbol.params or name in func.symbol.locals


def _last_name(dotted: str) -> str:
    return dotted.rpartition(".")[2]


def _is_class_name(name: str) -> bool:
    return name[:1].isupper() and not name.isupper()


def _is_data_call(callee: list[str] | None) -> bool:
    return bool(callee) and len(callee) > 1 and callee[-1] in _DATA_METHODS


def _library_node(name: str) -> str:
    top = name.split(".")[0]
    return f"{'stdlib' if top in sys.stdlib_module_names else 'external'}:{top}"
