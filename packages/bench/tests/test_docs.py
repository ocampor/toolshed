import shutil
from pathlib import Path

import griffe
import pytest

from bench.docs.files import Reference, reference_documents, stale_reference, write_reference
from bench.docs.render import Document, Members

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE = Path(__file__).parent.parent / "example" / "src"


def found_by_name(module: griffe.Module) -> list[str]:
    return [f"models.{name}" for name in module["models"].classes]


def sample_reference(members: tuple[str, ...] | Members) -> Reference:
    document = Document("Models", "The sample's models.", members, (("About", "models"),))
    return Reference("sample", "<!-- generated -->\n", {"reference/models": document})


@pytest.fixture
def source(tmp_path: Path) -> Path:
    shutil.copytree(EXAMPLE / "sample", tmp_path / "sample")
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
