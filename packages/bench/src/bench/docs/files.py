from pathlib import Path
from typing import NamedTuple

from bench.docs.render import Document, load_package, render


class Reference(NamedTuple):
    """What one consumer documents; ``header`` opens every generated file."""

    package: str
    header: str
    documents: dict[str, Document]


def reference_documents(reference: Reference, source: Path) -> dict[str, str]:
    """Every generated document, keyed by its doc name."""
    module = load_package(reference.package, source)
    return {name: render(module, document, reference.header) for name, document in reference.documents.items()}


def reference_dir(reference: Reference, source: Path) -> Path:
    return source / reference.package / "docs" / "reference"


def write_reference(reference: Reference, source: Path) -> list[str]:
    """Write every document under ``source``; answer the names that changed."""
    target = reference_dir(reference, source)
    target.mkdir(parents=True, exist_ok=True)
    changed = []
    for name, text in reference_documents(reference, source).items():
        path = target / f"{Path(name).name}.md"
        if not path.exists() or path.read_text() != text:
            path.write_text(text)
            changed.append(name)
    for orphan in orphans(reference, source):
        orphan.unlink()
        changed.append(f"removed {orphan.name}")
    return changed


def orphans(reference: Reference, source: Path) -> list[Path]:
    """Files left behind by a document that was renamed or dropped."""
    wanted = {f"{Path(name).name}.md" for name in reference.documents}
    target = reference_dir(reference, source)
    if not target.exists():
        return []
    return sorted(path for path in target.glob("*.md") if path.name not in wanted)


def stale_reference(reference: Reference, source: Path) -> list[str]:
    """What a rebuild would change: drift, missing files and orphans alike."""
    target = reference_dir(reference, source)
    stale = [
        name
        for name, text in reference_documents(reference, source).items()
        if not (path := target / f"{Path(name).name}.md").exists() or path.read_text() != text
    ]
    return stale + [f"orphan {path.name}" for path in orphans(reference, source)]
