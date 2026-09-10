import asyncio
import re
import shlex
from pathlib import Path, PurePosixPath
from typing import Any, get_args

import click
import pytest
import yaml
from click.testing import CliRunner
from yaml_engine.compile import compile_condition

from llm_browser.cli import main
from llm_browser.constants import SKILL_NAME
from llm_browser.flow_pipeline import resolve_flow_text
from llm_browser.flows import load_flow_document, load_flow_text
from llm_browser.html import SanitizeLevel, sanitize_html_fragment
from llm_browser.models import WaitState
from llm_browser.skill_install import (
    bundle_files,
    skill_destination,
    skill_text,
)

FRONTMATTER = f"---\nname: {SKILL_NAME}\n"

BUNDLE = [
    PurePosixPath("SKILL.md"),
    PurePosixPath("reference/DRIVERS.md"),
    PurePosixPath("reference/FLOWS.md"),
    PurePosixPath("reference/FLOW_PATTERNS.md"),
]

# A command line in the skill: an inline code span, or a line inside a fence.
COMMAND_LINE = re.compile(r"(?:^|`)(llm-browser [^`\n]*)", re.MULTILINE)

# `state: visible` in YAML samples and `--state visible` on command lines.
STATE_VALUE = re.compile(r"(?:state:|--state)\s+([a-z_]+)")

YAML_FENCE = re.compile(r"```yaml\n(.*?)```", re.DOTALL)

# One element carrying every attribute class the level table makes a claim about.
PROBE_FRAGMENT = (
    '<div id="i" class="c" role="r" data-testid="d" aria-label="a" placeholder="p"'
    ' name="n" title="t" style="color:red" href="h" src="s" value="v" type="text"'
    ' alt="al"><span>x</span><script>1</script><!--c--></div>'
)

GLOBAL_OPTIONS = {opt: param for param in main.params for opt in param.opts}


@pytest.fixture
def bundle_text() -> str:
    """Every file the skill installs, concatenated — one corpus to assert against."""
    return "\n".join(
        source.read_text(encoding="utf-8") for source in bundle_files().values()
    )


@pytest.fixture
def skill_lines() -> list[str]:
    """Every `llm-browser ...` invocation in the skill, backslash continuations joined."""
    text = skill_text().replace("\\\n", " ")
    return [match.group(1).strip() for match in COMMAND_LINE.finditer(text)]


@pytest.fixture
def bundle_steps(bundle_text: str) -> list[Any]:
    """Every step of every ```yaml fence in the bundle, as a validated model.

    A fence is either a whole flow document or a bare list of steps; anything
    else (a comment-only snippet) carries no steps to check.
    """
    steps = []
    for fence in YAML_FENCE.findall(bundle_text):
        parsed = yaml.safe_load(fence)
        if isinstance(parsed, dict) and "steps" in parsed:
            steps.extend(load_documented_flow(fence).steps)
        elif isinstance(parsed, list):
            steps.extend(load_documented_flow("steps:\n" + fence).steps)
    return steps


class StubFlowRepository:
    """Any `run-flow` reference resolves to an empty child.

    The docs illustrate composition with filenames that have no file; the
    reference itself is not what these tests check.
    """

    async def get(self, ref: str) -> str:
        return "steps: []"


def load_documented_flow(text: str) -> Any:
    """Load a documented flow the way the CLI would, sub-flow refs included."""
    document = asyncio.run(resolve_flow_text(text, StubFlowRepository()))
    return load_flow_document(document)


def resolve_command(tokens: list[str]) -> tuple[click.Command, list[str]]:
    """Walk the CLI group down to the command `tokens` names; return it and the rest.

    Group-level options may precede the subcommand, so they are consumed first.
    """
    command: click.Command = main
    rest = list(tokens)
    while isinstance(command, click.Group) and rest:
        head = rest[0]
        if head in GLOBAL_OPTIONS:
            rest = rest[1:] if GLOBAL_OPTIONS[head].is_flag else rest[2:]
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


def kept_attributes(level: SanitizeLevel) -> set[str]:
    """The attributes `level` actually leaves on PROBE_FRAGMENT's root element."""
    rendered = sanitize_html_fragment(PROBE_FRAGMENT, level=level)
    return set(re.findall(r'([\w-]+)="', rendered.split(">", 1)[0]))


def test_show_starts_with_frontmatter() -> None:
    result = CliRunner().invoke(main, ["skill", "show"])
    assert result.exit_code == 0
    assert result.output.startswith(FRONTMATTER)


def test_show_needs_no_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_BROWSER_DRIVER", "definitely-not-a-driver")
    result = CliRunner().invoke(main, ["skill", "show"])
    assert result.exit_code == 0


def test_bundle_ships_the_reference_docs() -> None:
    assert sorted(bundle_files()) == BUNDLE


def test_install_creates_the_whole_bundle(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["skill", "install", "--dest", str(tmp_path)])
    target = skill_destination(tmp_path)
    assert result.exit_code == 0
    assert str(target / "SKILL.md") in result.output
    assert (
        sorted(
            PurePosixPath(path.relative_to(target).as_posix())
            for path in target.rglob("*")
            if path.is_file()
        )
        == BUNDLE
    )


def test_skill_links_resolve_inside_the_bundle(tmp_path: Path) -> None:
    CliRunner().invoke(main, ["skill", "install", "--dest", str(tmp_path)])
    target = skill_destination(tmp_path)
    referenced = set(
        re.findall(r"`(reference/[\w.]+)`", (target / "SKILL.md").read_text())
    )
    assert referenced
    for link in referenced:
        assert (target / link).is_file(), f"SKILL.md links to a missing {link}"


def test_install_refuses_to_overwrite(tmp_path: Path) -> None:
    runner = CliRunner()
    runner.invoke(main, ["skill", "install", "--dest", str(tmp_path)])
    entry = skill_destination(tmp_path) / "SKILL.md"
    entry.write_text("mine")
    result = runner.invoke(main, ["skill", "install", "--dest", str(tmp_path)])
    assert result.exit_code != 0
    assert "already exists" in result.output
    assert entry.read_text() == "mine"


def test_install_force_overwrites(tmp_path: Path) -> None:
    runner = CliRunner()
    runner.invoke(main, ["skill", "install", "--dest", str(tmp_path)])
    entry = skill_destination(tmp_path) / "SKILL.md"
    entry.write_text("mine")
    result = runner.invoke(
        main, ["skill", "install", "--dest", str(tmp_path), "--force"]
    )
    assert result.exit_code == 0
    assert entry.read_text() == skill_text()


def test_install_reports_a_file_in_the_destination_path(tmp_path: Path) -> None:
    (tmp_path / ".claude").write_text("not a directory")
    result = CliRunner().invoke(main, ["skill", "install", "--dest", str(tmp_path)])
    assert result.exit_code != 0
    assert "is a file" in result.output
    assert "--force" not in result.output


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


def test_bundle_wait_states_are_real(bundle_text: str) -> None:
    named = set(STATE_VALUE.findall(bundle_text))
    assert named, "the bundle should name wait states"
    assert named <= set(get_args(WaitState)), f"unknown wait states: {named}"


def test_bundle_yaml_fences_load(bundle_steps: list[Any]) -> None:
    """Every YAML example is a flow the library actually accepts."""
    assert len(bundle_steps) > 10


@pytest.mark.parametrize(
    "action, field, expected",
    [
        ("click", "dispatch", True),
        ("wait_for", "settle", 800),
        ("type", "delay", 30),
        ("pick", "value", "USD"),
    ],
)
def test_step_fields_the_docs_teach_survive_validation(
    action: str, field: str, expected: object
) -> None:
    """A field pydantic silently drops would make the docs teach a no-op."""
    document = f"steps:\n - {{name: s, selector: '#x', action: {action}, {field}: {expected!r}}}"
    step = load_flow_text(document).steps[0]
    assert getattr(step, field) == expected


def test_extract_value_attribute_survives_validation() -> None:
    document = (
        "steps:\n - {name: s, selector: '#x', action: read, "
        "extract: {cp: {attribute: value}}}"
    )
    step = load_flow_text(document).steps[0]
    assert step.extract["cp"].attribute == "value"


def test_bundle_when_predicates_compile(bundle_steps: list[Any]) -> None:
    """`when:` is `list[dict]` — unvalidated at load, so a bad predicate only
    blows up mid-run. Compile every documented one here instead."""
    predicates = [cond for step in bundle_steps for cond in step.when]
    assert predicates, "the bundle should show `when:` predicates"
    for raw in predicates:
        if "element_exists" in raw or "element_missing" in raw:
            key = "element_exists" if "element_exists" in raw else "element_missing"
            assert "selector" in raw[key], f"{raw} has no selector"
            continue
        compile_condition(raw)


def test_bundle_condition_table_predicates_compile(bundle_text: str) -> None:
    """The FLOWS.md condition table is prose, not YAML — compile its rows too."""
    rows = re.findall(r"\| `\{ (field: .*?) \}` \|", bundle_text)
    assert rows, "the condition table should list field predicates"
    for row in rows:
        compile_condition(yaml.safe_load("{" + row + "}"))


def test_level_table_matches_the_sanitizer(bundle_text: str) -> None:
    """The `--level` guidance is derived from `html.py`; keep it that way."""
    claims = {
        SanitizeLevel.LOW: (
            {"data-testid", "aria-label", "role", "placeholder", "id"},
            {"style"},
        ),
        SanitizeLevel.MEDIUM: (
            {"id", "class", "href", "src"},
            {"data-testid", "aria-label", "role", "placeholder", "style"},
        ),
        SanitizeLevel.HIGH: ({"id", "class"}, {"href", "src", "role", "placeholder"}),
        SanitizeLevel.XHIGH: (
            {"id", "role", "placeholder", "name"},
            {"class", "data-testid", "aria-label", "href", "src"},
        ),
    }
    for level, (present, absent) in claims.items():
        kept = kept_attributes(level)
        assert present <= kept, f"{level.value} lost {present - kept}"
        assert not (absent & kept), f"{level.value} kept {absent & kept}"
    assert "`role` and `placeholder` survive at `xhigh`" in bundle_text
    assert "every attribute except `style`" in bundle_text
