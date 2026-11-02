"""Command line entry point."""

from __future__ import annotations

import time
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from codemap.model import Graph, dump_graph, load_graph
from codemap.pipeline import analyze_repo
from codemap.render.mermaid import render_mermaid

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Visualize the structure of a Python repository.",
)


class Format(StrEnum):
    mermaid = "mermaid"


class Level(StrEnum):
    package = "package"
    module = "module"


@app.command()
def analyze(
    repo: Annotated[Path, typer.Argument(exists=True, file_okay=False, help="Repository root.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Output directory.")] = Path("out"),
    jobs: Annotated[int | None, typer.Option(help="Parser processes (default: CPU count).")] = None,
) -> None:
    """Analyze a repository and write graph.json."""
    started = time.perf_counter()
    graph = analyze_repo(repo, jobs=jobs)
    elapsed = time.perf_counter() - started

    out.mkdir(parents=True, exist_ok=True)
    target = out / "graph.json"
    target.write_text(dump_graph(graph) + "\n", encoding="utf-8")

    typer.echo(_summary(graph, elapsed))
    typer.echo(f"Wrote {target}")


@app.command()
def serve(
    repo: Annotated[Path, typer.Argument(exists=True, file_okay=False, help="Repository root.")],
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 8700,
    host: Annotated[str, typer.Option(help="Interface to bind.")] = "127.0.0.1",
    open_browser: Annotated[bool, typer.Option("--open/--no-open", help="Open a browser.")] = True,
    jobs: Annotated[int | None, typer.Option(help="Parser processes (default: CPU count).")] = None,
) -> None:
    """Analyze a repository and explore it in the browser."""
    import threading
    import webbrowser

    import uvicorn

    from codemap.server.app import create_app

    started = time.perf_counter()
    graph = analyze_repo(repo, jobs=jobs)
    typer.echo(_summary(graph, time.perf_counter() - started))

    url = f"http://{host}:{port}/"
    typer.echo(f"Serving {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(create_app(repo, graph), host=host, port=port, log_level="warning")


@app.command()
def render(
    graph_file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="graph.json")],
    fmt: Annotated[Format, typer.Option("--format", "-f")] = Format.mermaid,
    level: Annotated[Level, typer.Option(help="Node granularity.")] = Level.module,
    focus: Annotated[
        str | None, typer.Option(help="Only edges touching this package or module, e.g. app.api.")
    ] = None,
    include_external: Annotated[
        bool, typer.Option(help="Show stdlib and third-party imports.")
    ] = False,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Default: stdout.")] = None,
) -> None:
    """Render graph.json in another format."""
    graph = load_graph(graph_file)
    result = render_mermaid(graph, level.value, focus, include_external)
    for warning in result.warnings:
        typer.secho(f"warning: {warning}", fg=typer.colors.YELLOW, err=True)
    if output is None:
        typer.echo(result.text, nl=False)
    else:
        output.write_text(result.text, encoding="utf-8")
        typer.echo(f"Wrote {output}", err=True)


def _summary(graph: Graph, elapsed: float) -> str:
    kinds = Counter(n.kind for n in graph.nodes)
    targets = Counter(e.target.partition(":")[0] for e in graph.edges if e.kind == "imports")
    internal = targets["mod"] + targets["pkg"]

    issues = []
    cycles = [i for i in graph.issues if i.kind == "cycle"]
    if runtime := sum(1 for i in cycles if i.runtime):
        issues.append(f"{runtime} runtime cycles")
    if deferred := len(cycles) - runtime:
        issues.append(f"{deferred} type-only/lazy cycles")
    other = Counter(i.kind for i in graph.issues if i.kind != "cycle")
    issues += [f"{count} {kind.replace('_', ' ')}s" for kind, count in sorted(other.items())]

    return "\n".join(
        [
            f"Analyzed {kinds['module']} modules in {kinds['package']} packages ({elapsed:.1f}s)",
            f"  symbols: {kinds['class']} classes, {kinds['function']} functions, "
            f"{kinds['method']} methods",
            f"  imports: {internal} internal, {targets['stdlib']} stdlib, "
            f"{targets['external']} external",
            f"  issues:  {', '.join(issues) or 'none'}",
        ]
    )
