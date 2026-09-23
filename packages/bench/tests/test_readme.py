import importlib.util
import shutil
import zipfile
from pathlib import Path
from types import ModuleType

import pytest
from hatchling.build import build_wheel

ROOT = Path(__file__).parent.parent
EXAMPLE = ROOT / "example"


def load_readme_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("readme", ROOT / "scripts" / "readme.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_readme_blocks_match_the_example() -> None:
    text = (ROOT / "README.md").read_text()
    assert load_readme_script().render(text, EXAMPLE) == text


def test_example_builds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "example"
    shutil.copytree(EXAMPLE, project)
    monkeypatch.chdir(project)

    wheel = build_wheel(str(tmp_path / "dist"))

    with zipfile.ZipFile(tmp_path / "dist" / wheel) as built:
        text = built.read("sample/docs/reference/models.md").decode()
    assert text == (ROOT / "tests" / "fixtures" / "models.md").read_text()
