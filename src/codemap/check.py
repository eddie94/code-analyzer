"""`codemap check`: turn issues into a pass/fail result for CI."""

from __future__ import annotations

from collections import Counter

from codemap.config import CheckKind
from codemap.model import Graph, Issue

_LABELS = {
    "layer_violation": "layer violation",
    "cycle": "import cycle",
    "parse_error": "parse error",
    "unresolved_import": "unresolved import",
}


def failing_issues(graph: Graph, fail_on: list[CheckKind]) -> list[Issue]:
    """Issues of the requested kinds. Only direct import-time cycles count as `cycle`."""
    result = []
    for issue in graph.issues:
        if issue.kind not in fail_on:
            continue
        if issue.kind == "cycle" and not (issue.runtime and issue.through_init is False):
            continue
        result.append(issue)
    return result


def format_text(graph: Graph, issues: list[Issue]) -> str:
    if not issues:
        return "codemap check: no problems"
    counts = Counter(_LABELS[i.kind] for i in issues)
    summary = ", ".join(f"{n} {label}{'s' if n > 1 else ''}" for label, n in sorted(counts.items()))
    lines = [f"codemap check: {len(issues)} problem{'s' if len(issues) > 1 else ''} ({summary})"]
    for issue in issues:
        lines.append(f"  {_location(graph, issue)}  {_message(graph, issue)}")
    return "\n".join(lines)


def format_github(graph: Graph, issues: list[Issue]) -> str:
    """GitHub Actions workflow commands, shown as annotations on the changed files."""
    lines = []
    for issue in issues:
        path = _path(graph, issue)
        props = [f"file={path}"] if path else []
        if issue.line:
            props.append(f"line={issue.line}")
        props.append(f"title=codemap {_LABELS[issue.kind]}")
        message = _message(graph, issue).replace("%", "%25").replace("\n", "%0A")
        lines.append(f"::error {','.join(props)}::{message}")
    return "\n".join(lines)


def _path(graph: Graph, issue: Issue) -> str | None:
    node = next((n for n in graph.nodes if n.id == issue.nodes[0]), None)
    return node.path if node else None


def _location(graph: Graph, issue: Issue) -> str:
    path = _path(graph, issue) or issue.nodes[0]
    return f"{path}:{issue.line}" if issue.line else path


def _message(graph: Graph, issue: Issue) -> str:
    if issue.kind == "cycle" and issue.examples:
        names = {n.id: n.qualname for n in graph.nodes}
        cycle = issue.examples[0]
        chain = " -> ".join(names.get(m, m) for m in [*cycle, cycle[0]])
        return f"{issue.message}: {chain}"
    return issue.message
