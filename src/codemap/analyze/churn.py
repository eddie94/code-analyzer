"""Change frequency from git history, and hotspots (churn x complexity)."""

from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path

from codemap.model import Metrics, Node


def git_churn(root: Path, days: int) -> dict[str, int] | None:
    """Commits touching each .py file (relative to `root`) in the last `days` days.

    Returns None when git is unavailable or no .py file under `root` is tracked
    (outside a work tree, or an ignored directory such as a virtualenv).
    """
    try:
        tracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--", "*.py"],
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        ).stdout
        if not tracked.strip():
            return None
        out = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "log",
                f"--since={days}.days",
                "--format=",
                "--name-only",
                "--no-renames",
                "--relative",
                "--",
                "*.py",
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=120,
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return dict(Counter(line for line in out.splitlines() if line))


def apply_churn(nodes: dict[str, Node], churn: dict[str, int]) -> None:
    """Set `churn` and `hotspot` on modules, and roll them up to packages.

    A module's hotspot is its churn times its highest function complexity: code
    that is both complicated and frequently changed. Packages take the sum of
    churn and the largest module hotspot.
    """
    for node in nodes.values():
        if node.kind != "module" or node.metrics is None or node.path is None:
            continue
        metrics = node.metrics
        metrics.churn = churn.get(node.path, 0)
        metrics.hotspot = metrics.churn * (metrics.max_complexity or 1)

        parent = node.parent
        while parent is not None:
            package = nodes[parent]
            if package.kind == "package":
                if package.metrics is None:
                    package.metrics = Metrics()
                package.metrics.churn = (package.metrics.churn or 0) + metrics.churn
                package.metrics.hotspot = max(package.metrics.hotspot or 0, metrics.hotspot)
            parent = package.parent
