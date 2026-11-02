from pathlib import Path

import pytest

from codemap.cache import CACHE_VERSION, ExtractCache, info_from_json, info_to_json
from codemap.extract import extract_all, parse_source
from codemap.model import dump_graph
from codemap.pipeline import analyze_repo
from codemap.scan import SourceFile

FIXTURE = Path(__file__).parent / "fixtures" / "shop"


@pytest.fixture(autouse=True)
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "cache"
    monkeypatch.setenv("CODEMAP_CACHE_DIR", str(directory))
    return directory


def test_round_trip():
    info = parse_source(
        b"from . import a as b\nif TYPE_CHECKING:\n    import x\n"
        b"class C(Base[T]):\n    async def m(self):\n        pass\n"
    )
    assert info_from_json(info_to_json(info)) == info


def test_cached_analysis_is_identical():
    fresh = dump_graph(analyze_repo(FIXTURE, timestamp=False))
    first = dump_graph(analyze_repo(FIXTURE, timestamp=False, cache=True))
    second = dump_graph(analyze_repo(FIXTURE, timestamp=False, cache=True))
    assert fresh == first == second


def test_hits_and_invalidation(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("import b\n")
    (repo / "b.py").write_text("X = 1\n")
    files = [SourceFile("a.py", "a", False), SourceFile("b.py", "b", False)]

    first = ExtractCache(repo)
    extract_all(repo, files, jobs=1, cache=first)
    assert first.hits == 0

    (repo / "b.py").write_text("import a\n")
    second = ExtractCache(repo)
    infos = extract_all(repo, files, jobs=1, cache=second)
    assert second.hits == 1  # a.py unchanged, b.py re-parsed
    assert infos[1].imports[0].module == "a"


def test_stale_or_corrupt_cache_is_ignored(cache_dir: Path, tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("X = 1\n")
    cache = ExtractCache(repo)
    cache_dir.mkdir()
    cache.path.write_text("{not json")
    assert ExtractCache(repo).get("a.py", "x") is None
    cache.path.write_text('{"version": "old", "entries": {"a.py": {"digest": "x", "info": {}}}}')
    assert ExtractCache(repo).get("a.py", "x") is None
    assert CACHE_VERSION != "old"
