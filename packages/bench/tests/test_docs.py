import shutil
import zipfile
from pathlib import Path

import griffe
import pytest
from hatchling.build import build_wheel

from bench.docs.files import Reference, reference_documents, stale_reference, write_reference
from bench.docs.render import Document, Members

FIXTURES = Path(__file__).parent / "fixtures"


def found_by_name(module: griffe.Module) -> list[str]:
    return [f"models.{name}" for name in module["models"].classes]


def sample_reference(members: tuple[str, ...] | Members) -> Reference:
    document = Document("Models", "The sample's models.", members, (("About", "models"),))
    return Reference("sample", "<!-- generated -->\n", {"reference/models": document})


@pytest.fixture
def source(tmp_path: Path) -> Path:
    shutil.copytree(FIXTURES / "sample", tmp_path / "sample")
    return tmp_path


@pytest.mark.parametrize("members", [("models.Answer",), found_by_name], ids=["tuple", "callable"])
def test_render_matches_expected_markdown(members: tuple[str, ...] | Members, source: Path) -> None:
    rendered = reference_documents(sample_reference(members), source)
    assert rendered["reference/models"] == (FIXTURES / "models.md").read_text()


def test_drift_is_detected_and_repaired(source: Path) -> None:
    reference = sample_reference(("models.Answer",))
    write_reference(reference, source)
    target = source / "sample" / "docs" / "reference"
    (target / "models.md").write_text("edited")
    (target / "dropped.md").write_text("left behind")

    assert stale_reference(reference, source) == ["reference/models", "orphan dropped.md"]
    assert write_reference(reference, source) == ["reference/models", "removed dropped.md"]
    assert stale_reference(reference, source) == []


def test_hook_writes_the_reference_into_the_wheel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shutil.copytree(FIXTURES / "sample", tmp_path / "src" / "sample")
    (tmp_path / "hatch_build.py").write_text("from bench.docs.hook import ReferenceDocsHook  # noqa: F401\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "sample"\nversion = "0"\n'
        '[tool.hatch.build.targets.wheel]\npackages = ["src/sample"]\n'
        '[tool.hatch.build.hooks.custom]\npath = "hatch_build.py"\npackage = "sample"\n'
    )
    monkeypatch.chdir(tmp_path)

    wheel = build_wheel(str(tmp_path / "dist"))

    with zipfile.ZipFile(tmp_path / "dist" / wheel) as built:
        text = built.read("sample/docs/reference/models.md").decode()
    assert text == (FIXTURES / "models.md").read_text()
