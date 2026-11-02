"""Find Python files and map them to dotted module names."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pathspec

from codemap.config import Config

_SKIP_DIRS = {"__pycache__", "node_modules", "site-packages", "venv"}
# Only skipped at the repository top level; nested packages may use these names.
_SKIP_TOP_DIRS = {"build", "dist"}


@dataclass(frozen=True)
class SourceFile:
    path: str  # repo-relative, POSIX separators
    module: str  # dotted name; for __init__.py this is the package name
    is_package: bool


@dataclass
class ScanResult:
    root: Path
    source_roots: list[str]
    files: list[SourceFile]
    packages: dict[str, str]  # dotted package name -> repo-relative directory


def scan_repo(root: Path, config: Config) -> ScanResult:
    root = root.resolve()
    include = _spec(config.include)
    exclude = _spec(config.exclude)
    paths = [
        p
        for p in _list_python_files(root)
        if not _skipped(p)
        and (include is None or include.match_file(p))
        and (exclude is None or not exclude.match_file(p))
    ]
    roots = _source_roots(root, paths, config)

    files: list[SourceFile] = []
    packages: dict[str, str] = {}
    seen: set[str] = set()
    for path in paths:
        named = _module_name(path, roots)
        if named is None:
            continue
        module, is_package, prefix = named
        if module in seen:
            continue
        seen.add(module)
        files.append(SourceFile(path, module, is_package))

        parts = module.split(".")
        depth = len(parts) if is_package else len(parts) - 1
        for i in range(1, depth + 1):
            name = ".".join(parts[:i])
            packages.setdefault(name, "/".join([*prefix, *parts[:i]]))

    return ScanResult(root, roots, files, packages)


def _spec(patterns: list[str]) -> pathspec.PathSpec | None:
    return pathspec.GitIgnoreSpec.from_lines(patterns) if patterns else None


def _skipped(path: str) -> bool:
    dirs = PurePosixPath(path).parts[:-1]
    if dirs and dirs[0] in _SKIP_TOP_DIRS:
        return True
    return any(d.startswith(".") or d in _SKIP_DIRS for d in dirs)


def _list_python_files(root: Path) -> list[str]:
    if (root / ".git").exists():
        try:
            out = subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "ls-files",
                    "-z",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                    "--",
                    "*.py",
                ],
                capture_output=True,
                check=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError):
            pass
        else:
            listed = out.decode("utf-8", "surrogateescape").split("\0")
            return sorted({p for p in listed if p and (root / p).is_file()})
    return _walk(root)


def _walk(root: Path) -> list[str]:
    gitignore = root / ".gitignore"
    ignored = (
        pathspec.GitIgnoreSpec.from_lines(gitignore.read_text(encoding="utf-8").splitlines())
        if gitignore.is_file()
        else None
    )
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root).as_posix()
        prefix = "" if rel == "." else rel + "/"
        dirnames[:] = [
            d
            for d in dirnames
            if not d.startswith(".")
            and d not in _SKIP_DIRS
            and not (ignored and ignored.match_file(prefix + d + "/"))
        ]
        for name in filenames:
            path = prefix + name
            if name.endswith(".py") and not (ignored and ignored.match_file(path)):
                found.append(path)
    return sorted(found)


def _source_roots(root: Path, paths: list[str], config: Config) -> list[str]:
    if config.source_roots is not None:
        return [r.strip("/").removeprefix("./") or "." for r in config.source_roots]
    if any(p.startswith("src/") for p in paths) and not (root / "src" / "__init__.py").exists():
        return ["src"]
    return ["."]


def _module_name(path: str, roots: list[str]) -> tuple[str, bool, list[str]] | None:
    """Return (module, is_package, root parts) using the deepest matching source root.

    Files outside every configured root fall back to the repository root, so
    top-level tests and scripts still show up.
    """
    candidates = sorted((r for r in roots if r != "."), key=len, reverse=True)
    for root in [*candidates, "."]:
        if root == ".":
            rel, prefix = path, []
        elif path.startswith(root + "/"):
            rel, prefix = path[len(root) + 1 :], root.split("/")
        else:
            continue
        parts = list(PurePosixPath(rel).with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts.pop()
        if not parts:
            return None
        return ".".join(parts), is_package, prefix
    return None
