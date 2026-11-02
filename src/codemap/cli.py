"""Command line entry point."""

from __future__ import annotations

import time
import tomllib
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from codemap.config import Config, load_config
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


class CheckFormat(StrEnum):
    text = "text"
    github = "github"


class Level(StrEnum):
    package = "package"
    module = "module"


@app.command()
def analyze(
    repo: Annotated[Path, typer.Argument(exists=True, file_okay=False, help="Repository root.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Output directory.")] = Path("out"),
    jobs: Annotated[int | None, typer.Option(help="Parser processes (default: CPU count).")] = None,
    cache: Annotated[
        bool, typer.Option("--cache/--no-cache", help="Reuse results for unchanged files.")
    ] = True,
) -> None:
    """Analyze a repository and write graph.json."""
    started = time.perf_counter()
    graph = analyze_repo(repo, config=_config(repo), jobs=jobs, cache=cache, history=True)
    elapsed = time.perf_counter() - started

    out.mkdir(parents=True, exist_ok=True)
    target = out / "graph.json"
    target.write_text(dump_graph(graph) + "\n", encoding="utf-8")

    typer.echo(_summary(graph, elapsed))
    typer.echo(f"Wrote {target}")


@app.command()
def check(
    repo: Annotated[Path, typer.Argument(exists=True, file_okay=False, help="Repository root.")],
    fail_on: Annotated[
        list[str] | None,
        typer.Option(
            "--fail-on",
            help="Issue kinds that fail the check (repeatable): layer_violation, cycle, "
            "parse_error, unresolved_import. Default: [tool.codemap] fail_on.",
        ),
    ] = None,
    fmt: Annotated[CheckFormat, typer.Option("--format", help="Output format.")] = CheckFormat.text,
    jobs: Annotated[int | None, typer.Option(help="Parser processes (default: CPU count).")] = None,
    cache: Annotated[
        bool, typer.Option("--cache/--no-cache", help="Reuse results for unchanged files.")
    ] = True,
) -> None:
    """Fail (exit 1) on layer violations and import cycles; for CI."""
    from codemap.check import failing_issues, format_github, format_text

    config = _config(repo, {"fail_on": fail_on} if fail_on else {})
    graph = analyze_repo(repo, config=config, jobs=jobs, cache=cache, history=True)
    issues = failing_issues(graph, config.fail_on)
    if fmt is CheckFormat.github:
        if issues:
            typer.echo(format_github(graph, issues))
        typer.echo(format_text(graph, issues), err=True)
    else:
        typer.echo(format_text(graph, issues))
    raise typer.Exit(1 if issues else 0)


@app.command()
def export(
    repo: Annotated[Path, typer.Argument(exists=True, file_okay=False, help="Repository root.")],
    output: Annotated[Path, typer.Option("--output", "-o", help="HTML file to write.")] = Path(
        "codemap.html"
    ),
    jobs: Annotated[int | None, typer.Option(help="Parser processes (default: CPU count).")] = None,
    cache: Annotated[
        bool, typer.Option("--cache/--no-cache", help="Reuse results for unchanged files.")
    ] = True,
) -> None:
    """Write a single HTML file that opens without a server (no source preview)."""
    from codemap.render.export_html import ViewerNotBuilt, export_html

    started = time.perf_counter()
    graph = analyze_repo(repo, config=_config(repo), jobs=jobs, cache=cache, history=True)
    try:
        html = export_html(graph)
    except ViewerNotBuilt as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from e
    output.write_text(html, encoding="utf-8")
    typer.echo(_summary(graph, time.perf_counter() - started))
    typer.echo(f"Wrote {output} ({len(html.encode()) / 1_000_000:.1f} MB)")


@app.command()
def serve(
    repo: Annotated[Path, typer.Argument(exists=True, file_okay=False, help="Repository root.")],
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 8700,
    host: Annotated[str, typer.Option(help="Interface to bind.")] = "127.0.0.1",
    open_browser: Annotated[bool, typer.Option("--open/--no-open", help="Open a browser.")] = True,
    jobs: Annotated[int | None, typer.Option(help="Parser processes (default: CPU count).")] = None,
    cache: Annotated[
        bool, typer.Option("--cache/--no-cache", help="Reuse results for unchanged files.")
    ] = True,
) -> None:
    """Analyze a repository and explore it in the browser."""
    import threading
    import webbrowser

    import uvicorn

    from codemap.server.app import create_app

    started = time.perf_counter()
    graph = analyze_repo(repo, config=_config(repo), jobs=jobs, cache=cache, history=True)
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


def _config(repo: Path, overrides: dict | None = None) -> Config:
    """Project config with CLI overrides, reported as a usage error when invalid."""
    try:
        config = load_config(repo.resolve())
        if overrides:
            config = Config.model_validate({**config.model_dump(), **overrides})
    except (ValidationError, tomllib.TOMLDecodeError) as e:
        raise typer.BadParameter(str(e)) from e
    return config


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
