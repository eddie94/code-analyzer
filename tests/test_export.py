import json
import re
from pathlib import Path

import pytest

from codemap.pipeline import analyze_repo
from codemap.render.export_html import ViewerNotBuilt, export_html

FIXTURE = Path(__file__).parent / "fixtures" / "shop"

INDEX = """<!doctype html>
<html>
  <head>
    <script type="module" crossorigin src="/assets/index-abc.js"></script>
    <link rel="modulepreload" crossorigin href="/assets/chunk.js">
    <link rel="stylesheet" crossorigin href="/assets/index-abc.css">
  </head>
  <body><div id="root"></div></body>
</html>
"""


@pytest.fixture
def static(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(INDEX)
    (tmp_path / "assets" / "index-abc.js").write_text('const s = "</script>"; boot();')
    (tmp_path / "assets" / "index-abc.css").write_text("body { color: red }")
    return tmp_path


def test_inlines_assets_and_data(static: Path):
    graph = analyze_repo(FIXTURE, timestamp=False)
    html = export_html(graph, static)
    assert "/assets/" not in html
    assert "<style>body { color: red }</style>" in html
    assert '<script type="module">const s = "<\\/script>"; boot();</script>' in html

    data = re.search(
        r'<script id="codemap-data" type="application/json">(.*?)</script>', html, re.S
    )
    assert data is not None
    assert json.loads(data.group(1))["meta"]["root"] == str(FIXTURE.resolve())


def test_embedded_data_cannot_close_the_script_tag(static: Path):
    graph = analyze_repo(FIXTURE, timestamp=False)
    graph.nodes[0].doc = "</script><script>alert(1)</script>"
    html = export_html(graph, static)
    assert "alert(1)</script>" not in html
    data = re.search(r'id="codemap-data" type="application/json">(.*?)</script>', html, re.S)
    assert json.loads(data.group(1))["nodes"][0]["doc"] == "</script><script>alert(1)</script>"


def test_missing_build(tmp_path: Path):
    graph = analyze_repo(FIXTURE, timestamp=False)
    with pytest.raises(ViewerNotBuilt):
        export_html(graph, tmp_path)
