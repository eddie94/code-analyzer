"""Connections that frameworks make, not code: how a service starts and is wired up.

- Apps: module variables holding a FastAPI/Starlette/Flask app or router.
- Registration: which app a route or startup hook is decorated on, and routers
  mounted with include_router / register_blueprint.
- Launches: `uvicorn.run(app)` in code, and `uvicorn pkg.mod:app`, `python -m pkg`
  or `python path.py` in shell scripts, Dockerfiles, Procfiles and compose files.
- Shared state: module globals one function sets (typically a startup hook) and
  others read, e.g. `engine = Engine(...)` used by every request handler.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from codemap.analyze.calls import CallGraph, Func
from codemap.model import App, EntryPoint, Launch, SharedState
from codemap.scan import ScanResult

APP_CLASSES = {
    "fastapi.FastAPI": "fastapi",
    "fastapi.APIRouter": "router",
    "fastapi.routing.APIRouter": "router",
    "starlette.applications.Starlette": "starlette",
    "flask.Flask": "flask",
    "flask.Blueprint": "blueprint",
}
SERVE_CALLS = {"uvicorn.run", "hypercorn.asyncio.serve", "waitress.serve", "granian.Granian"}
_MOUNT_METHODS = {"include_router", "register_blueprint", "mount"}
_MAX_FILE_BYTES = 200_000

_ASSIGN = re.compile(r"""^\s*(?:export\s+)?([A-Za-z_]\w*)=(["']?)([^"'\s]*)\2\s*(?:#.*)?$""")
_VARIABLE = re.compile(r"\$\{(\w+)\}|\$(\w+)")
_SERVER = re.compile(
    r"\b(?:uvicorn|gunicorn|hypercorn|granian)\b.*?\b([A-Za-z_][\w.]*):([A-Za-z_]\w*)\b"
)
_PY_MODULE = re.compile(r"\bpython[\d.]*\s+(?:-\w+\s+)*-m\s+([A-Za-z_][\w.]*)")
_PY_FILE = re.compile(r"\b(?:python[\d.]*|fastapi\s+(?:run|dev))\s+(?:-\w+\s+)*([\w./-]+\.py)\b")


class Framework:
    def __init__(self, graph: CallGraph, scan: ScanResult) -> None:
        self.graph = graph
        self.scan = scan
        self.apps: dict[str, App] = {}  # app id -> App
        self._find_apps()
        self._find_includes()

    # ---------- apps and registration ----------

    def _find_apps(self) -> None:
        for module, variables in self.graph.module_vars.items():
            for name, values in variables.items():
                for value, owner in values:
                    if owner is not None or not value.call:
                        continue
                    library = self.graph.resolve_call(value.call, module, None).library
                    if library in APP_CLASSES:
                        app_id = f"app:{module}.{name}"
                        self.apps[app_id] = App(
                            id=app_id,
                            kind=APP_CLASSES[library],
                            name=f"{module}.{name}",
                            module=f"mod:{module}",
                        )

    def _app_of(self, parts: list[str] | None, module: str, func: Func | None) -> str | None:
        """The app a dotted name in `module` refers to, if any."""
        if not parts:
            return None
        ref = self.graph._ref(parts, module, func)
        if ref and ref.kind == "var" and not ref.rest and f"app:{ref.name}" in self.apps:
            return f"app:{ref.name}"
        return None

    def _find_includes(self) -> None:
        for func in self.graph.funcs.values():
            for site in func.symbol.calls:
                if not site.callee or site.callee[-1] not in _MOUNT_METHODS or not site.args:
                    continue
                parent = self._app_of(site.callee[:-1], func.module, func)
                child = self._app_of(site.args[-1].split("."), func.module, func)
                if parent and child and child not in self.apps[parent].includes:
                    self.apps[parent].includes.append(child)

    def assign_apps(self, entrypoints: list[EntryPoint]) -> None:
        """Set `EntryPoint.app` from the object the decorator hangs off."""
        for entry in entrypoints:
            func = self.graph.funcs.get(entry.target)
            if func is None:
                continue
            for decorator in func.symbol.entries:
                if decorator.owner and (app := self._app_of(decorator.owner, func.module, func)):
                    entry.app = app
                    break

    # ---------- launches ----------

    def launches(self) -> list[Launch]:
        found = self._code_launches() + self._command_launches()
        unique: dict[tuple, Launch] = {}
        for launch in found:
            unique.setdefault((launch.kind, launch.label, launch.target, launch.file), launch)
        return sorted(unique.values(), key=lambda x: (x.kind, x.file or "", x.line or 0, x.label))

    def _code_launches(self) -> list[Launch]:
        launches = []
        for func in self.graph.funcs.values():
            for site in func.symbol.calls:
                if not site.callee or not site.args:
                    continue
                call = self.graph.resolve_call(site.callee, func.module, func)
                is_flask_run = site.callee[-1] == "run" and self._app_of(
                    site.callee[:-1], func.module, func
                )
                if call.library not in SERVE_CALLS and not is_flask_run:
                    continue
                target = (
                    self._app_of(site.callee[:-1], func.module, func)
                    if is_flask_run
                    else self._target_of_argument(site.args[0], func)
                )
                launches.append(
                    Launch(
                        kind="code",
                        label=f"{site.text}({site.args[0] if not is_flask_run else ''})",
                        target=target,
                        source=func.id,
                        line=site.line,
                    )
                )
        return launches

    def _target_of_argument(self, argument: str, func: Func) -> str | None:
        if argument.startswith('"'):
            module, _, attr = argument.strip('"').partition(":")
            return self._server_target(module, attr)
        return self._app_of(argument.split("."), func.module, func)

    def _server_target(self, module: str, attr: str) -> str | None:
        if f"app:{module}.{attr}" in self.apps:
            return f"app:{module}.{attr}"
        if f"fn:{module}.{attr}" in self.graph.funcs:
            return f"fn:{module}.{attr}"
        return None

    def _command_launches(self) -> list[Launch]:
        modules_by_path = {f.path: f.module for f in self.scan.files}
        launches = []
        for path in _launch_files(self.scan.root):
            try:
                text = (self.scan.root / path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            variables: dict[str, str] = {}
            for number, raw in enumerate(text.splitlines(), start=1):
                if assignment := _ASSIGN.match(raw):
                    variables[assignment.group(1)] = assignment.group(3)
                    continue
                line = _substitute(raw, variables)
                command = " ".join(re.sub(r"""[\[\]",']""", " ", line).split())
                for target in self._command_targets(command, modules_by_path):
                    launches.append(
                        Launch(
                            kind="command",
                            label=command[:140],
                            target=target,
                            file=path,
                            line=number,
                        )
                    )
        return launches

    def _command_targets(self, command: str, modules_by_path: dict[str, str]) -> list[str | None]:
        if command.lstrip().startswith(("#", "echo ")):
            return []
        if server := _SERVER.search(command):
            return [self._server_target(server.group(1), server.group(2))]
        if module := _PY_MODULE.search(command):
            name = module.group(1)
            return [self._main_of(name) or self._main_of(f"{name}.__main__")]
        if file := _PY_FILE.search(command):
            written = file.group(1).lstrip("./")
            matches = [
                m for p, m in modules_by_path.items() if p == written or written.endswith(f"/{p}")
            ]
            return [self._main_of(matches[0]) if matches else None]
        return []

    def _main_of(self, module: str) -> str | None:
        for name in ("__main__", "__module__"):
            if f"fn:{module}.{name}" in self.graph.funcs:
                return f"fn:{module}.{name}"
        return None

    # ---------- shared state ----------

    def shared_state(self) -> list[SharedState]:
        states = []
        for module, variables in self.graph.module_vars.items():
            functions = [f for f in self.graph.funcs.values() if f.module == module]
            for name, values in variables.items():
                writers = sorted({owner.id for _, owner in values if owner is not None})
                if not writers:
                    continue
                readers = sorted(
                    f.id
                    for f in functions
                    if f.id not in writers
                    and name in f.symbol.reads
                    and name not in f.symbol.locals
                    and name not in f.symbol.arguments
                )
                if readers:
                    types = sorted(f"cls:{t}" for t in self.graph._var_types(module, name))
                    states.append(
                        SharedState(
                            name=f"{module}.{name}", writers=writers, readers=readers, types=types
                        )
                    )
        return sorted(states, key=lambda s: s.name)


def _substitute(line: str, variables: dict[str, str]) -> str:
    """Expand $VAR and ${VAR} from earlier simple assignments in the same file."""
    return _VARIABLE.sub(lambda m: variables.get(m.group(1) or m.group(2), m.group(0)), line)


def _launch_files(root: Path) -> list[str]:
    """Scripts and container files that may start the service."""
    try:
        listed = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8", "surrogateescape")
        paths = [p for p in listed.split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        paths = []
        for directory, dirs, files in os.walk(root):
            dirs[:] = [
                d for d in dirs if not d.startswith(".") and d not in ("node_modules", "venv")
            ]
            rel = Path(directory).relative_to(root)
            paths += [(rel / f).as_posix() for f in files]
    return sorted(p for p in paths if _is_launch_file(root, p))


def _is_launch_file(root: Path, path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if not (
        name.endswith((".sh", ".yml", ".yaml"))
        or name.startswith(("Dockerfile", "Procfile", "Makefile"))
        or name.endswith(".dockerfile")
    ):
        return False
    try:
        return (root / path).stat().st_size <= _MAX_FILE_BYTES
    except OSError:
        return False
