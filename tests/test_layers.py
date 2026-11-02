from pathlib import Path

import pytest

from codemap.analyze.layers import module_matches
from codemap.pipeline import analyze_repo

LAYERED = Path(__file__).parent / "fixtures" / "layered"


@pytest.mark.parametrize(
    ("qualname", "pattern", "expected"),
    [
        ("app.api.users", "app.api.*", True),
        ("app.api", "app.api.*", True),
        ("app.apis", "app.api.*", False),
        ("app.api.v1.users", "app.api.*", True),
        ("app.service", "app.service", True),
        ("other.api.users", "*.api.*", True),
    ],
)
def test_module_matches(qualname: str, pattern: str, expected: bool):
    assert module_matches(qualname, pattern) is expected


def test_layer_violations():
    graph = analyze_repo(LAYERED, timestamp=False)
    assert graph.meta.layers == ["api", "service", "repo"]
    layers = {n.qualname: n.layer for n in graph.nodes if n.kind == "module"}
    assert layers["app.api.users"] == "api"
    assert layers["app.repo"] == "repo"
    assert layers["app"] is None

    violations = [i for i in graph.issues if i.kind == "layer_violation"]
    # repo.db -> api.users is reported; its TYPE_CHECKING import of service is not.
    assert [(i.nodes, i.line, i.severity) for i in violations] == [
        (["mod:app.repo.db", "mod:app.api.users"], 3, "error")
    ]
    assert "(repo) imports app.api.users (api)" in violations[0].message
