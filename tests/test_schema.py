import json
from pathlib import Path

from codemap.model import graph_schema

SCHEMA = Path(__file__).parents[1] / "viewer" / "src" / "types" / "graph.schema.json"


def test_viewer_types_are_current():
    """Run `npm run gen:types` in viewer/ after changing codemap.model."""
    assert json.loads(SCHEMA.read_text()) == graph_schema()
