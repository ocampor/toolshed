"""The packaged Claude Code skill that teaches flow authoring, and its installer.

The skill ships as a bundle — ``SKILL.md`` plus the reference docs it links to —
because an installed skill that points at files living only in this repo sends
the reading agent looking for documentation it cannot reach.
"""

from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath

from llm_browser.constants import SKILL_DIR_NAME, SKILL_FILENAME, SKILL_NAME


def skill_root() -> Traversable:
    """The packaged skill directory, read through the package loader so it
    works from a wheel, an editable install or a zip import alike."""
    return files("llm_browser").joinpath(SKILL_DIR_NAME)


def bundle_files() -> dict[PurePosixPath, Traversable]:
    """Every file in the bundle, keyed by its path relative to the skill dir."""
    return dict(walk_bundle(skill_root(), PurePosixPath()))


def walk_bundle(
    node: Traversable, prefix: PurePosixPath
) -> list[tuple[PurePosixPath, Traversable]]:
    found: list[tuple[PurePosixPath, Traversable]] = []
    for child in node.iterdir():
        path = prefix / child.name
        if child.is_dir():
            found.extend(walk_bundle(child, path))
        else:
            found.append((path, child))
    return sorted(found)


def skill_text() -> str:
    """The packaged SKILL.md."""
    return skill_root().joinpath(SKILL_FILENAME).read_text(encoding="utf-8")


def skill_destination(dest: Path) -> Path:
    """The bundle's directory under ``dest``, a repo root."""
    return dest / ".claude" / "skills" / SKILL_NAME


def reject_file_in_path(target: Path) -> None:
    """``mkdir(parents=True)`` reports a file in the middle of the path as a
    bare ``FileExistsError``, which reads as "already installed" — say what is
    actually wrong instead."""
    for parent in reversed(target.parents):
        if parent.exists() and not parent.is_dir():
            raise NotADirectoryError(
                f"{parent} is a file, so {target} cannot be created"
            )


def install_skill(dest: Path, *, force: bool = False) -> Path:
    """Copy the bundle under ``dest``; refuse to clobber unless ``force``.

    Returns the installed ``SKILL.md``. Files the bundle no longer ships are
    left alone: an overwrite replaces what it brings, nothing more.
    """
    target = skill_destination(dest)
    entry = target / SKILL_FILENAME
    reject_file_in_path(entry)
    if entry.exists() and not force:
        raise FileExistsError(f"{entry} already exists; pass --force to overwrite")
    for relative, source in bundle_files().items():
        written = target / relative
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_bytes(source.read_bytes())
    return entry
