from pathlib import Path

import pytest

from codemap.model import Graph
from codemap.pipeline import analyze_repo

CATALOG = Path(__file__).parent / "fixtures" / "catalog"


@pytest.fixture(scope="module")
def graph() -> Graph:
    return analyze_repo(CATALOG, timestamp=False)


def calls(graph: Graph, source: str) -> dict[str, str]:
    return {e.target: e.confidence for e in graph.edges if e.kind == "calls" and e.source == source}


def test_entrypoints(graph: Graph):
    assert [(e.kind, e.label, e.target) for e in graph.entrypoints] == [
        ("route", "GET /books", "fn:catalog.web.find_books"),
        ("route", "GET /stats", "fn:catalog.admin.stats"),
        ("startup", "on startup", "fn:catalog.web.open_catalog"),
        ("main", "python catalog/web.py", "fn:catalog.web.__main__"),
        ("script", "catalog-warm", "fn:catalog.web.warm_up"),
    ]


def test_global_assigned_at_startup(graph: Graph):
    # `searcher` starts as None and is set in the startup hook.
    assert calls(graph, "fn:catalog.web.find_books") == {
        "meth:catalog.search.Searcher.search": "inferred"
    }
    assert calls(graph, "fn:catalog.web.open_catalog") == {
        "meth:catalog.search.Searcher.__init__": "exact",
        "cls:catalog.settings.Settings": "exact",
    }


def test_methods_attributes_and_libraries(graph: Graph):
    assert calls(graph, "meth:catalog.search.Searcher.search") == {
        "meth:catalog.search.Searcher.split": "exact",
        "meth:catalog.search.Searcher.remember": "exact",
        "meth:catalog.search.Searcher.artwork": "exact",
        "meth:catalog.search.Searcher.merge": "exact",
        "meth:catalog.shelf.Shelf.lookup": "inferred",  # self.shelf = Shelf()
        # self.backup: Store may hold a Store or a CachedStore, so both are candidates
        "meth:catalog.storage.Store.fetch": "candidates",
        "meth:catalog.storage.CachedStore.fetch": "candidates",
        "stdlib:asyncio": "exact",
    }
    edge = next(
        e
        for e in graph.edges
        if e.source.endswith("Searcher.search") and e.target == "stdlib:asyncio"
    )
    assert edge.names == ["asyncio.create_task", "asyncio.gather"]


def test_parameter_defaults_and_super(graph: Graph):
    # store: Store = CachedStore() -> the annotation and the default both count
    assert calls(graph, "meth:catalog.shelf.Shelf.lookup") == {
        "meth:catalog.storage.Store.fetch": "candidates",
        "meth:catalog.storage.CachedStore.fetch": "candidates",
        "meth:catalog.shelf.Shelf._sorted": "exact",
    }
    assert calls(graph, "meth:catalog.storage.CachedStore.fetch") == {
        "meth:catalog.storage.Store.fetch": "exact"
    }


def test_local_imports_and_return_types(graph: Graph):
    assert calls(graph, "meth:catalog.search.Searcher.artwork") == {
        "fn:catalog.covers.covers_for": "exact"
    }
    assert calls(graph, "fn:catalog.covers.covers_for") == {
        "fn:catalog.covers.connect": "exact",
        "meth:catalog.covers.CoverClient.download": "inferred",  # connect() -> CoverClient
    }
    download = next(e for e in graph.edges if e.source.endswith("CoverClient.download"))
    assert (download.target, download.names) == ("external:httpx", ["httpx.get"])


def test_main_block(graph: Graph):
    edge = next(e for e in graph.edges if e.source == "fn:catalog.web.__main__")
    assert (edge.target, edge.names) == ("external:uvicorn", ["uvicorn.run"])


def test_unresolved_calls_are_kept(graph: Graph):
    nodes = {n.id: n for n in graph.nodes}
    assert nodes["meth:catalog.search.Searcher.search"].unresolved_calls == []
    assert nodes["fn:catalog.web.warm_up"].unresolved_calls == []


def test_calls_on_call_results(graph: Graph):
    # Searcher(Settings()).split(...)
    assert (
        calls(graph, "fn:catalog.web.warm_up")["meth:catalog.search.Searcher.split"] == "inferred"
    )
