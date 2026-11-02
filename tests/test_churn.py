import subprocess
from pathlib import Path

from codemap.analyze.churn import git_churn
from codemap.pipeline import analyze_repo


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        check=True,
        capture_output=True,
    )


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    (repo / "pkg").mkdir(parents=True)
    git(repo, "init", "-q")
    (repo / "pkg" / "__init__.py").write_text("")
    (repo / "pkg" / "a.py").write_text("def f(x):\n    return 1 if x else 2\n")
    (repo / "pkg" / "b.py").write_text("X = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "one")
    (repo / "pkg" / "a.py").write_text("def f(x):\n    return 3 if x else 4\n")
    git(repo, "commit", "-q", "-am", "two")
    return repo


def test_git_churn(tmp_path: Path):
    repo = make_repo(tmp_path)
    assert git_churn(repo, 90) == {"pkg/__init__.py": 1, "pkg/a.py": 2, "pkg/b.py": 1}
    # Paths are relative to the analyzed directory, even inside a larger repository.
    assert git_churn(repo / "pkg", 90) == {"__init__.py": 1, "a.py": 2, "b.py": 1}
    assert git_churn(tmp_path, 90) is None  # not a git work tree

    (repo / ".gitignore").write_text("vendor/\n")
    (repo / "vendor").mkdir()
    (repo / "vendor" / "lib.py").write_text("")
    assert git_churn(repo / "vendor", 90) is None  # ignored, so no history


def test_hotspot_metrics(tmp_path: Path):
    repo = make_repo(tmp_path)
    graph = analyze_repo(repo, timestamp=False, history=True)
    nodes = {n.id: n for n in graph.nodes}
    assert graph.meta.churn_days == 90
    a = nodes["mod:pkg.a"].metrics
    assert (a.churn, a.max_complexity, a.hotspot) == (2, 2, 4)
    assert nodes["mod:pkg.b"].metrics.hotspot == 1
    assert (nodes["pkg:pkg"].metrics.churn, nodes["pkg:pkg"].metrics.hotspot) == (4, 4)


def test_history_is_off_by_default(tmp_path: Path):
    graph = analyze_repo(make_repo(tmp_path), timestamp=False)
    assert graph.meta.churn_days is None
    assert all(n.metrics is None or n.metrics.churn is None for n in graph.nodes)
