"""A single self-contained HTML file: the built viewer with the graph inlined.

The export opens from disk without a server, so source preview is unavailable;
the viewer detects the embedded data and hides it.
"""

from __future__ import annotations

import re
from pathlib import Path

from codemap.model import Graph, dump_graph
from codemap.server.app import STATIC_DIR

_SCRIPT = re.compile(r'<script type="module" crossorigin src="/(assets/[^"]+\.js)"></script>')
_STYLESHEET = re.compile(r'<link rel="stylesheet" crossorigin href="/(assets/[^"]+\.css)">')
_PRELOAD = re.compile(r'\s*<link rel="modulepreload"[^>]*>')


class ViewerNotBuilt(RuntimeError):
    pass


def export_html(graph: Graph, static_dir: Path = STATIC_DIR) -> str:
    index = static_dir / "index.html"
    if not index.is_file():
        raise ViewerNotBuilt(f"{index} is missing; run `npm install && npm run build` in viewer/")
    html = index.read_text(encoding="utf-8")

    # Only `<` can end a <script> element early; inside JSON it only occurs in strings.
    data = dump_graph(graph).replace("<", "\\u003c")
    data_tag = f'<script id="codemap-data" type="application/json">{data}</script>'

    def inline_script(match: re.Match[str]) -> str:
        code = (static_dir / match.group(1)).read_text(encoding="utf-8")
        code = code.replace("</script", "<\\/script")
        return f'{data_tag}\n    <script type="module">{code}</script>'

    def inline_style(match: re.Match[str]) -> str:
        css = (static_dir / match.group(1)).read_text(encoding="utf-8")
        return f"<style>{css.replace('</style', '<\\/style')}</style>"

    html, scripts = _SCRIPT.subn(inline_script, html)
    if scripts != 1:
        raise ViewerNotBuilt(f"expected one entry script in {index}, found {scripts}")
    html = _STYLESHEET.sub(inline_style, html)
    return _PRELOAD.sub("", html)
