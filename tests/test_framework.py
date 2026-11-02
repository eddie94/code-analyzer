from pathlib import Path

import pytest

from codemap.model import Graph
from codemap.pipeline import analyze_repo

CATALOG = Path(__file__).parent / "fixtures" / "catalog"


@pytest.fixture(scope="module")
def graph() -> Graph:
    return analyze_repo(CATALOG, timestamp=False)


def test_apps_and_registration(graph: Graph):
    apps = {a.id: a for a in graph.apps}
    assert set(apps) == {"app:catalog.web.api", "app:catalog.admin.admin"}
    assert apps["app:catalog.web.api"].kind == "fastapi"
    assert apps["app:catalog.admin.admin"].kind == "router"
    assert apps["app:catalog.web.api"].includes == ["app:catalog.admin.admin"]
    owners = {e.label: e.app for e in graph.entrypoints}
    assert owners["GET /books"] == "app:catalog.web.api"
    assert owners["on startup"] == "app:catalog.web.api"
    assert owners["GET /stats"] == "app:catalog.admin.admin"


def test_launches(graph: Graph):
    launches = [(x.kind, x.file, x.line, x.label, x.target) for x in graph.launches]
    assert launches == [
        ("code", None, 30, "uvicorn.run(api)", "app:catalog.web.api"),
        ("command", "Dockerfile", 3, "CMD python -m catalog.web", "fn:catalog.web.__main__"),
        (
            "command",
            "run.sh",
            3,
            "exec uvicorn catalog.web:api --port 8100 --reload",  # ${TARGET} filled in
            "app:catalog.web.api",
        ),
    ]
    assert graph.launches[0].source == "fn:catalog.web.__main__"


def test_shared_state(graph: Graph):
    [state] = graph.state
    assert state.name == "catalog.web.searcher"
    assert state.writers == ["fn:catalog.web.open_catalog"]
    assert state.readers == ["fn:catalog.web.find_books"]
    assert state.types == ["cls:catalog.search.Searcher"]


def test_flow_steps(graph: Graph):
    nodes = {n.id: n for n in graph.nodes}
    flow = nodes["meth:catalog.search.Searcher.search"].flow
    steps = {s.text: s for s in flow.steps}
    gather = steps["asyncio.gather"]
    assert steps["self.shelf.lookup"].group == gather.line
    assert steps["self.artwork"].group == gather.line
    assert steps["self.remember"].background
    assert not steps["self.merge"].background
    assert steps["self.merge"].targets == ["meth:catalog.search.Searcher.merge"]
    assert [(e.kind, e.value, [c.text for c in e.context]) for e in flow.exits] == [
        ("raise", "ValueError('query too long')", ["len(words) > 8"]),
        ("return", "self.backup.fetch(query)", ["not titles"]),
        ("return", "self.merge(titles, art)", []),
    ]
    # the module's import-time code is its own pseudo-function
    module_code = nodes["fn:catalog.web.__module__"].flow
    assert [s.text for s in module_code.steps] == ["FastAPI", "api.include_router"]


def test_flow_values(graph: Graph):
    nodes = {n.id: n for n in graph.nodes}
    flow = nodes["meth:catalog.search.Searcher.search"].flow
    steps = {s.text: s for s in flow.steps}
    assert flow.params == ["query"]
    assert steps["self.split"].inputs == ["query"]
    assert steps["self.split"].assigns == ["words"]
    lookup = steps["self.shelf.lookup"]
    assert (lookup.inputs, lookup.receiver) == (["words"], "self.shelf")
    assert not lookup.nested  # a concurrent lane, not a plain argument
    # a method passed along reads the object it is called on, not the method itself
    assert steps["asyncio.gather"].inputs == ["self.shelf", "words"]
    assert steps["asyncio.gather"].assigns == ["titles", "art"]
    assert steps["self.merge"].inputs == ["titles", "art"]
    assert [e.inputs for e in flow.exits] == [[], ["self.backup", "query"], ["titles", "art"]]
