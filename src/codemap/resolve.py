"""Resolve imports and base classes to modules and classes in the repository."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

from codemap.extract import ModuleInfo, RawImport
from codemap.scan import SourceFile

_MAX_HOPS = 20

# A module-level name bound by an import:
#   ("module", "a.b", None)  from `import a.b as x` (or `import a` -> ("module", "a", None))
#   ("from", "a.b", "name")  from `from a.b import name`
Binding = tuple[str, str, str | None]


@dataclass
class Resolved:
    target: str | None  # node id; None when the import could not be resolved
    names: list[str] = field(default_factory=list)
    via: list[str] = field(default_factory=list)
    problem: str | None = None


class Resolver:
    def __init__(
        self, modules: dict[str, tuple[SourceFile, ModuleInfo]], packages: set[str]
    ) -> None:
        self.modules = modules
        self.packages = packages
        self.classes = {
            f"{name}.{sym.qualname}"
            for name, (_, info) in modules.items()
            for sym in info.symbols
            if sym.kind == "class"
        }
        self._bindings: dict[str, dict[str, Binding]] = {}

    def resolve_import(self, sf: SourceFile, imp: RawImport) -> list[Resolved]:
        if imp.names is None:
            assert imp.module is not None
            return [self._module(imp.module, [], f"cannot resolve module '{imp.module}'")]

        written = "." * imp.level + (imp.module or "")
        base = self.absolute(sf, imp.level, imp.module)
        if not base:
            return [
                Resolved(None, problem=f"relative import '{written}' goes beyond the top level")
            ]

        results: list[Resolved] = []
        for name, _ in imp.names:
            if name == "*":
                results.append(self._module(base, ["*"], f"cannot resolve module '{written}'"))
                continue
            sub = f"{base}.{name}"
            if sub in self.modules:
                results.append(Resolved(f"mod:{sub}", [name]))
            elif sub in self.packages:
                results.append(Resolved(f"pkg:{sub}", [name]))
            elif base in self.modules:
                owner, via = self.locate(base, name)
                results.append(Resolved(f"mod:{owner}", [name], [f"mod:{v}" for v in via]))
            else:
                problem = f"cannot resolve 'from {written} import {name}'"
                results.append(self._module(base, [name], problem))
        return results

    def absolute(self, sf: SourceFile, level: int, module: str | None) -> str | None:
        if level == 0:
            return module
        package = sf.module.split(".") if sf.is_package else sf.module.split(".")[:-1]
        up = level - 1
        if up > len(package):
            return None
        parts = package[: len(package) - up]
        if module:
            parts += module.split(".")
        return ".".join(parts) or None

    def _module(self, full: str, names: list[str], problem: str) -> Resolved:
        """Resolve a dotted module path to a module, package, stdlib or external node."""
        parts = full.split(".")
        for i in range(len(parts), 0, -1):
            name = ".".join(parts[:i])
            if name in self.modules or name in self.packages:
                if i < len(parts):
                    return Resolved(None, names, problem=problem)
                kind = "mod" if name in self.modules else "pkg"
                return Resolved(f"{kind}:{name}", names)
        top = parts[0]
        kind = "stdlib" if top in sys.stdlib_module_names else "external"
        return Resolved(f"{kind}:{top}", names)

    def locate(self, module: str, name: str) -> tuple[str, list[str]]:
        """Follow re-exports of `name` from `module` to the module that defines it.

        Returns the defining module (or the last internal module on the chain) and
        the re-exporting modules passed through.
        """
        via: list[str] = []
        for _ in range(_MAX_HOPS):
            if name in self.modules[module][1].defined:
                break
            binding = self.bindings(module).get(name)
            if binding is None:
                break
            kind, target, target_name = binding
            if kind == "module":
                if target in self.modules:
                    via.append(module)
                    module = target
                break
            sub = f"{target}.{target_name}"
            if sub in self.modules:
                via.append(module)
                module = sub
                break
            if target not in self.modules:
                break
            via.append(module)
            module, name = target, target_name
        return module, via

    def resolve_class(self, module: str, parts: list[str], hops: int = 0) -> str | None:
        """Resolve a dotted reference used in `module` (e.g. a base class) to a class qualname."""
        if hops > _MAX_HOPS or not parts or module not in self.modules:
            return None
        head, rest = parts[0], parts[1:]
        if head in self.modules[module][1].defined:
            qualname = ".".join([module, *parts])
            return qualname if qualname in self.classes else None
        binding = self.bindings(module).get(head)
        if binding is None:
            # Attribute access on a module object reached through a binding: `pkg.sub.Base`.
            sub = f"{module}.{head}"
            return self.resolve_class(sub, rest, hops + 1) if hops and rest else None
        kind, target, target_name = binding
        if kind == "module":
            return self.resolve_class(target, rest, hops + 1)
        sub = f"{target}.{target_name}"
        if sub in self.modules:
            return self.resolve_class(sub, rest, hops + 1)
        return self.resolve_class(target, [target_name, *rest], hops + 1)

    def bindings(self, module: str) -> dict[str, Binding]:
        cached = self._bindings.get(module)
        if cached is not None:
            return cached
        sf, info = self.modules[module]
        result: dict[str, Binding] = {}
        for imp in info.imports:
            if not imp.module_level or imp.type_only:
                continue
            if imp.names is None:
                assert imp.module is not None
                if imp.alias:
                    result[imp.alias] = ("module", imp.module, None)
                else:
                    top = imp.module.split(".")[0]
                    result[top] = ("module", top, None)
                continue
            base = self.absolute(sf, imp.level, imp.module)
            if not base:
                continue
            for name, asname in imp.names:
                if name != "*":
                    result[asname or name] = ("from", base, name)
        self._bindings[module] = result
        return result
