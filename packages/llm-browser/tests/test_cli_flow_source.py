"""Tests for the CLI's flow sources: --flow PATH, --flow -, --flow-yaml."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from click.testing import CliRunner

from llm_browser.cli import (
    build_flow,
    file_path,
    flow_source_from_options,
    main,
    run_cli_flow,
)
from llm_browser.models import FlowError, FlowSuccess
from llm_browser.session import BrowserSession

FLOW_DOCUMENT = {
    "steps": [{"name": "s1", "action": "goto", "url": "https://example.com"}]
}
FLOW_YAML = yaml.dump(FLOW_DOCUMENT)
PARENT_YAML = yaml.dump(
    {"steps": [{"name": "c", "action": "run-flow", "flow": "child.yaml"}]}
)
CHILD_YAML = yaml.dump(
    {"steps": [{"name": "c1", "action": "goto", "url": "https://child.example"}]}
)


def _with_child_in_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "child.yaml").write_text(CHILD_YAML)
    monkeypatch.chdir(tmp_path)


def _mock_session(tmp_path: Path) -> MagicMock:
    from llm_browser.behavior import Behavior

    session = MagicMock(spec=BrowserSession)
    session.session_dir = tmp_path
    session.behavior = Behavior.off()
    session._behavior_runtime = session.behavior.runtime()
    session.capture = "screenshot"
    session.driver = MagicMock()
    session.get_page.return_value = MagicMock()
    return session


# --- source selection ---


def test_flow_source_from_options_reads_inline_text() -> None:
    source = flow_source_from_options(None, FLOW_YAML)
    assert (source.text, source.base_dir) == (FLOW_YAML, Path.cwd())


def test_flow_source_from_options_reads_a_file(tmp_path: Path) -> None:
    path = tmp_path / "flow.yaml"
    path.write_text(FLOW_YAML)

    source = flow_source_from_options(str(path), None)

    assert source.base_dir == tmp_path.resolve()
    assert build_flow(source).steps[0].name == "s1"


@pytest.mark.parametrize(
    ("flow_path", "flow_yaml"), [(None, None), ("flow.yml", FLOW_YAML)]
)
def test_flow_source_from_options_requires_exactly_one_source(
    flow_path: str | None, flow_yaml: str | None
) -> None:
    with pytest.raises(Exception, match="exactly one"):
        flow_source_from_options(flow_path, flow_yaml)


# --- running ---


def test_run_cli_flow_runs_inline_text_without_touching_disk(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    source = flow_source_from_options(None, FLOW_YAML)

    result = run_cli_flow(session, build_flow(source), {}, from_step=None)

    assert isinstance(result, FlowSuccess)
    assert session.goto.call_args.args == ("https://example.com",)


def test_run_command_runs_a_flow_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "flow.yaml"
    path.write_text(FLOW_YAML)
    session = _mock_session(tmp_path)
    monkeypatch.setattr("llm_browser.cli.build_session", lambda **kwargs: session)

    result = CliRunner().invoke(main, ["run", "--flow", str(path)])

    assert result.exit_code == 0
    assert session.goto.call_args.args == ("https://example.com",)


# --- validate ---


@pytest.mark.parametrize(
    ("args", "stdin"),
    [
        (["validate", "--flow-yaml", FLOW_YAML], ""),
        (["validate", "--flow", "-"], FLOW_YAML),
    ],
)
def test_validate_accepts_every_inline_source(args: list[str], stdin: str) -> None:
    result = CliRunner().invoke(main, args, input=stdin)
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "ok": True,
        "flow": "<inline>",
        "step_count": 1,
        "subflow_count": 0,
    }


def test_validate_accepts_a_flow_file(tmp_path: Path) -> None:
    path = tmp_path / "flow.yaml"
    path.write_text(FLOW_YAML)

    result = CliRunner().invoke(main, ["validate", "--flow", str(path)])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["flow"] == str(path)


def test_validate_reports_a_parse_error_with_the_format() -> None:
    result = CliRunner().invoke(main, ["validate", "--flow-yaml", "steps: [\n - a\n"])
    assert result.exit_code == 1
    assert "invalid flow yaml" in json.loads(result.stderr)["message"]


def test_validate_rejects_two_sources() -> None:
    result = CliRunner().invoke(
        main, ["validate", "--flow", "f.yml", "--flow-yaml", FLOW_YAML]
    )
    assert result.exit_code == 2
    assert "exactly one" in result.output


def test_run_cli_flow_fills_the_retry_hint_with_the_flow_path(
    tmp_path: Path,
) -> None:
    path = tmp_path / "flow.yaml"
    path.write_text(
        yaml.dump({"steps": [{"name": "boom", "action": "click", "selector": "#a"}]})
    )
    session = _mock_session(tmp_path)
    session.find.side_effect = TimeoutError("element missing")
    source = flow_source_from_options(str(path), None)

    result = run_cli_flow(
        session, build_flow(source), {}, from_step=None, flow_path=file_path(str(path))
    )

    assert isinstance(result, FlowError)
    assert result.retry_hint is not None
    assert result.retry_hint.flow_path == str(path.resolve())


@pytest.mark.parametrize("flow_path", [None, "-"])
def test_file_path_is_none_for_text_sources(flow_path: str | None) -> None:
    assert file_path(flow_path) is None


def test_an_empty_flow_path_is_a_usage_error() -> None:
    result = CliRunner().invoke(main, ["validate", "--flow", ""])
    assert result.exit_code == 2
    assert "--flow needs a path" in result.output


# --- cwd-relative sub-flow refs ---


def test_run_cli_flow_resolves_a_sibling_ref_from_the_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with_child_in_cwd(tmp_path, monkeypatch)
    session = _mock_session(tmp_path)
    source = flow_source_from_options(None, PARENT_YAML)

    result = run_cli_flow(session, build_flow(source), {}, from_step=None)

    assert isinstance(result, FlowSuccess)
    assert session.goto.call_args.args == ("https://child.example",)


@pytest.mark.parametrize(
    "args, stdin",
    [
        (["validate", "--flow-yaml", PARENT_YAML], ""),
        (["validate", "--flow", "-"], PARENT_YAML),
    ],
)
def test_validate_resolves_a_sibling_ref_from_the_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str], stdin: str
) -> None:
    _with_child_in_cwd(tmp_path, monkeypatch)

    result = CliRunner().invoke(main, args, input=stdin)

    assert result.exit_code == 0
    assert json.loads(result.stdout)["subflow_count"] == 1
