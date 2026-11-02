import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codemap.model import Graph
from codemap.pipeline import analyze_repo
from codemap.server.app import create_app

FIXTURE = Path(__file__).parent / "fixtures" / "shop"


@pytest.fixture(scope="module")
def graph() -> Graph:
    return analyze_repo(FIXTURE, timestamp=False)


@pytest.fixture
def client(graph: Graph, tmp_path: Path) -> TestClient:
    return TestClient(create_app(FIXTURE, graph, static_dir=tmp_path))


def test_graph(client: TestClient):
    response = client.get("/api/graph")
    assert response.status_code == 200
    body = json.loads(response.text)
    assert any(n["id"] == "mod:shop.models" for n in body["nodes"])


def test_source(client: TestClient):
    response = client.get("/api/source", params={"path": "src/shop/notify.py"})
    assert response.status_code == 200
    assert response.json()["text"].startswith("from shop.services import billing")


@pytest.mark.parametrize(
    "path", ["../../../pyproject.toml", "/etc/hosts", "src/shop/missing.py", "src"]
)
def test_source_rejects_other_paths(client: TestClient, path: str):
    assert client.get("/api/source", params={"path": path}).status_code == 404


def test_viewer_not_built(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "not built" in response.text


def test_serves_built_viewer(graph: Graph, tmp_path: Path):
    (tmp_path / "index.html").write_text("<title>viewer</title>")
    client = TestClient(create_app(FIXTURE, graph, static_dir=tmp_path))
    assert "viewer" in client.get("/").text
    assert client.get("/api/graph").status_code == 200
