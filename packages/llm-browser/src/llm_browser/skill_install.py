"""The packaged Claude Code skill that teaches flow authoring, and its installer."""

from importlib.resources import files
from pathlib import Path

from llm_browser.constants import SKILL_DIR_NAME, SKILL_FILENAME, SKILL_NAME


def skill_text() -> str:
    """The packaged SKILL.md, read from the installed package data."""
    resource = files("llm_browser").joinpath(SKILL_DIR_NAME, SKILL_FILENAME)
    return resource.read_text(encoding="utf-8")


def skill_destination(dest: Path) -> Path:
    """Where ``dest`` (a repo root) wants the skill file."""
    return dest / ".claude" / "skills" / SKILL_NAME / SKILL_FILENAME


def install_skill(dest: Path, *, force: bool = False) -> Path:
    """Write the packaged skill under ``dest``; refuse to clobber unless ``force``."""
    target = skill_destination(dest)
    if target.exists() and not force:
        raise FileExistsError(f"{target} already exists; pass --force to overwrite")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(skill_text(), encoding="utf-8")
    return target
