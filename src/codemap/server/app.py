"""Local HTTP server: graph and source APIs plus the built viewer."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from codemap.model import Graph, dump_graph

STATIC_DIR = Path(__file__).parent / "static"

_NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>codemap</title>
<p>The viewer is not built. Run <code>npm install && npm run build</code> in <code>viewer/</code>,
or start <code>npm run dev</code> there and open the URL it prints.</p>"""


class Source(BaseModel):
    path: str
    text: str


def create_app(root: Path, graph: Graph, static_dir: Path = STATIC_DIR) -> FastAPI:
    root = root.resolve()
    body = dump_graph(graph, compact=True)
    # Only files that were analyzed can be read back, never arbitrary paths.
    readable = {n.path for n in graph.nodes if n.kind == "module" and n.path}

    app = FastAPI(title="codemap", docs_url=None, redoc_url=None)

    @app.get("/api/graph")
    def get_graph() -> Response:
        return Response(body, media_type="application/json")

    @app.get("/api/source")
    def get_source(path: str) -> Source:
        if path not in readable:
            raise HTTPException(404, "not an analyzed file")
        file = (root / path).resolve()
        if not file.is_relative_to(root) or not file.is_file():
            raise HTTPException(404, "file not found")
        return Source(path=path, text=file.read_text(encoding="utf-8", errors="replace"))

    if (static_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="viewer")
    else:

        @app.get("/", response_class=HTMLResponse)
        def not_built() -> str:
            return _NOT_BUILT

    return app
