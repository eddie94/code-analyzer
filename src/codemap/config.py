"""Load `[tool.codemap]` from pyproject.toml, or `.codemap.toml`."""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class Layer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    modules: list[str]


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # None means auto-detect (src layout or the repository root).
    source_roots: list[str] | None = None
    # Gitignore-style patterns relative to the repository root.
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    hide_external: bool = True
    layers: list[Layer] = Field(default_factory=list)


def load_config(root: Path) -> Config:
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        section = data.get("tool", {}).get("codemap")
        if section is not None:
            return Config.model_validate(section)
    standalone = root / ".codemap.toml"
    if standalone.is_file():
        return Config.model_validate(tomllib.loads(standalone.read_text(encoding="utf-8")))
    return Config()
