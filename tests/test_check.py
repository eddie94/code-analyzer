from pathlib import Path

from typer.testing import CliRunner

from codemap.cli import app

LAYERED = Path(__file__).parent / "fixtures" / "layered"
runner = CliRunner()


def test_check_fails_on_layers_and_cycles():
    result = runner.invoke(app, ["check", str(LAYERED)])
    assert result.exit_code == 1
    lines = result.output.splitlines()
    assert lines[0] == "codemap check: 2 problems (1 import cycle, 1 layer violation)"
    assert "app/repo/db.py:3  app.repo.db (repo) imports app.api.users (api)" in result.output
    assert "app.api.users -> app.service.users -> app.repo.db -> app.api.users" in result.output


def test_fail_on_can_be_narrowed():
    result = runner.invoke(app, ["check", str(LAYERED), "--fail-on", "layer_violation"])
    assert result.exit_code == 1
    assert "1 problem (1 layer violation)" in result.output


def test_github_annotations():
    result = runner.invoke(
        app, ["check", str(LAYERED), "--fail-on", "layer_violation", "--format", "github"]
    )
    assert result.exit_code == 1
    assert result.stdout.startswith(
        "::error file=app/repo/db.py,line=3,title=codemap layer violation::app.repo.db (repo)"
    )


def test_clean_repository_passes(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "a.py").write_text("from pkg import b\n")
    (tmp_path / "pkg" / "b.py").write_text("X = 1\n")
    result = runner.invoke(app, ["check", str(tmp_path)])
    assert result.exit_code == 0
    assert result.output.strip() == "codemap check: no problems"


def test_invalid_fail_on_is_rejected():
    result = runner.invoke(app, ["check", str(LAYERED), "--fail-on", "nope"])
    assert result.exit_code != 0
