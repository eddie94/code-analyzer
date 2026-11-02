from pathlib import Path

from codemap.config import Config, load_config
from codemap.scan import scan_repo


def write(root: Path, files: dict[str, str]) -> None:
    for path, content in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)


def test_src_layout_and_fallback_root(tmp_path: Path):
    write(
        tmp_path,
        {
            "src/app/__init__.py": "",
            "src/app/core/db.py": "",
            "tests/test_db.py": "",
            "setup.py": "",
        },
    )
    scan = scan_repo(tmp_path, Config())
    assert scan.source_roots == ["src"]
    assert {f.module: f.is_package for f in scan.files} == {
        "app": True,
        "app.core.db": False,
        "setup": False,
        "tests.test_db": False,
    }
    assert scan.packages == {"app": "src/app", "app.core": "src/app/core", "tests": "tests"}


def test_ignored_files(tmp_path: Path):
    write(
        tmp_path,
        {
            ".gitignore": "generated/\n",
            "app/main.py": "",
            "app/generated/x.py": "",
            "app/__pycache__/x.py": "",
            ".venv/lib/x.py": "",
            "build/lib/x.py": "",
            "app/build/x.py": "",
            "app/migrations/0001.py": "",
        },
    )
    scan = scan_repo(tmp_path, Config(exclude=["**/migrations/**"]))
    assert sorted(f.path for f in scan.files) == ["app/build/x.py", "app/main.py"]


def test_load_config_from_pyproject(tmp_path: Path):
    write(
        tmp_path,
        {
            "pyproject.toml": '[tool.codemap]\nsource_roots = ["lib"]\nexclude = ["a/**"]\n',
        },
    )
    config = load_config(tmp_path)
    assert config.source_roots == ["lib"]
    assert config.exclude == ["a/**"]
