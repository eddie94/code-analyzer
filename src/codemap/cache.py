"""Per-file extraction cache, keyed by file content.

The cache lives in the user's cache directory, never inside the analyzed
repository, and is plain JSON: a cache file planted in a repository can
neither be picked up nor execute code.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from codemap.extract import EXTRACT_VERSION, ModuleInfo, RawImport, Symbol

CACHE_VERSION = f"{EXTRACT_VERSION}:py{sys.version_info.major}.{sys.version_info.minor}"


def default_cache_dir() -> Path:
    if override := os.environ.get("CODEMAP_CACHE_DIR"):
        return Path(override)
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "codemap"


class ExtractCache:
    def __init__(self, root: Path, directory: Path | None = None) -> None:
        key = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
        self.path = (directory or default_cache_dir()) / f"{key}.json"
        self._old: dict[str, dict] = {}
        self._new: dict[str, dict] = {}
        self.hits = 0
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("version") == CACHE_VERSION:
                self._old = data["entries"]
        except (OSError, ValueError, KeyError, TypeError):
            pass

    @staticmethod
    def digest(content: bytes) -> str:
        return hashlib.sha1(content, usedforsecurity=False).hexdigest()

    def get(self, path: str, digest: str) -> ModuleInfo | None:
        entry = self._old.get(path)
        if not entry or entry.get("digest") != digest:
            return None
        try:
            info = info_from_json(entry["info"])
        except (KeyError, TypeError, ValueError):
            return None
        self._new[path] = entry
        self.hits += 1
        return info

    def put(self, path: str, digest: str, info: ModuleInfo) -> None:
        self._new[path] = {"digest": digest, "info": info_to_json(info)}

    def save(self) -> None:
        """Write entries used in this run; files that disappeared are dropped."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.path.parent, delete=False, suffix=".tmp"
            ) as tmp:
                json.dump({"version": CACHE_VERSION, "entries": self._new}, tmp)
            os.replace(tmp.name, self.path)
        except OSError:
            pass


def info_to_json(info: ModuleInfo) -> dict:
    data = asdict(info)
    data["defined"] = sorted(info.defined)
    return data


def info_from_json(data: dict) -> ModuleInfo:
    imports = [
        RawImport(**{**i, "names": None if i["names"] is None else [tuple(n) for n in i["names"]]})
        for i in data["imports"]
    ]
    symbols = [Symbol(**{**s, "range": tuple(s["range"])}) for s in data["symbols"]]
    return ModuleInfo(
        **{**data, "defined": set(data["defined"]), "imports": imports, "symbols": symbols}
    )
