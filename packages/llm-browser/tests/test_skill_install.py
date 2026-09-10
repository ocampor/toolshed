import re
import shlex
from pathlib import Path
from typing import get_args

import click
import pytest
from click.testing import CliRunner

from llm_browser.cli import main
from llm_browser.constants import SKILL_NAME
from llm_browser.models import WaitState
from llm_browser.skill_install import skill_destination, skill_text

FRONTMATTER = f"---\nname: {SKILL_NAME}\n"

# A command line in the skill: an inline code span, or a line inside a fence.
COMMAND_LINE = re.compile(r"(?:^|`)(llm-browser [^`\n]*)", re.MULTILINE)

# `state: visible` in YAML samples and `--state visible` on command lines.
STATE_VALUE = re.compile(r"(?:state:|--state)\s+([a-z_]+)")


@pytest.fixture
def skill_lines() -> list[str]:
    """Every `llm-browser ...` invocation in the skill, backslash continuations joined."""
    text = skill_text().replace("\\\n", " ")
    return [match.group(1).strip() for match in COMMAND_LINE.finditer(text)]


GLOBAL_OPTIONS = {opt: param for param in main.params for opt in param.opts}


def resolve_command(tokens: list[str]) -> tuple[click.Command, list[str]]:
    """Walk the CLI group down to the command `tokens` names; return it and the rest.

    Group-level options may precede the subcommand, so they are consumed first.
    """
    command: click.Command = main
    rest = list(tokens)
    while isinstance(command, click.Group) and rest:
        head = rest[0]
        if head in GLOBAL_OPTIONS:
            rest = rest[2:] if not GLOBAL_OPTIONS[head].is_flag else rest[1:]
            continue
        if head.startswith("-"):
            break
        name = rest.pop(0)
        child = command.get_command(click.Context(command), name)
        assert child is not None, f"{name!r} is not a real llm-browser command"
        command = child
    return command, rest


def option_names(command: click.Command) -> set[str]:
    names = {opt for param in main.params for opt in param.opts}
    names.update(opt for param in command.params for opt in param.opts)
    names.update(opt for param in command.params for opt in param.secondary_opts)
    return names


def test_show_starts_with_frontmatter() -> None:
    result = CliRunner().invoke(main, ["skill", "show"])
    assert result.exit_code == 0
    assert result.output.startswith(FRONTMATTER)


def test_install_creates_the_skill_file(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["skill", "install", "--dest", str(tmp_path)])
    target = skill_destination(tmp_path)
    assert result.exit_code == 0
    assert str(target) in result.output
    assert target.read_text() == skill_text()


def test_install_refuses_to_overwrite(tmp_path: Path) -> None:
    runner = CliRunner()
    runner.invoke(main, ["skill", "install", "--dest", str(tmp_path)])
    skill_destination(tmp_path).write_text("mine")
    result = runner.invoke(main, ["skill", "install", "--dest", str(tmp_path)])
    assert result.exit_code != 0
    assert "already exists" in result.output
    assert skill_destination(tmp_path).read_text() == "mine"


def test_install_force_overwrites(tmp_path: Path) -> None:
    runner = CliRunner()
    runner.invoke(main, ["skill", "install", "--dest", str(tmp_path)])
    skill_destination(tmp_path).write_text("mine")
    result = runner.invoke(
        main, ["skill", "install", "--dest", str(tmp_path), "--force"]
    )
    assert result.exit_code == 0
    assert skill_destination(tmp_path).read_text() == skill_text()


def test_skill_commands_are_real(skill_lines: list[str]) -> None:
    assert skill_lines, "the skill should show real command lines"
    for line in skill_lines:
        tokens = shlex.split(line)[1:]
        command, rest = resolve_command(tokens)
        allowed = option_names(command)
        unknown = [
            token
            for token in rest
            if token.startswith("--") and token.split("=")[0] not in allowed
        ]
        assert not unknown, f"{line!r} uses flags {unknown} that {command.name} lacks"


def test_skill_wait_states_are_real() -> None:
    named = set(STATE_VALUE.findall(skill_text()))
    assert named, "the skill should name wait states"
    assert named <= set(get_args(WaitState)), f"unknown wait states: {named}"
