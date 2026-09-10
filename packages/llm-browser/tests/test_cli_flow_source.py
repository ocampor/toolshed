"""Tests for the CLI's flow sources: --flow PATH, --flow -, --flow-yaml."""

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml
from click.testing import CliRunner

from llm_browser.cli import file_path, main, resolve_flow_options, run_cli_flow
from llm_browser.flows import load_flow_document
from llm_browser.models import Flow, FlowError, FlowSuccess
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


def _cli_flow(flow_path: str | None, flow_yaml: str | None = None) -> Flow:
    document = asyncio.run(resolve_flow_options(flow_path, flow_yaml))
    return load_flow_document(document)


def _resolve(flow_path: str | None, flow_yaml: str | None = None) -> dict[str, Any]:
    return asyncio.run(resolve_flow_options(flow_path, flow_yaml))


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


def test_inline_text_resolves_to_its_document() -> None:
    assert _resolve(None, FLOW_YAML) == FLOW_DOCUMENT


def test_a_flow_file_resolves_to_its_document(tmp_path: Path) -> None:
    path = tmp_path / "flow.yaml"
    path.write_text(FLOW_YAML)

    assert _cli_flow(str(path)).steps[0].name == "s1"


@pytest.mark.parametrize(
    ("flow_path", "flow_yaml"), [(None, None), ("flow.yml", FLOW_YAML)]
)
def test_exactly_one_source_is_required(
    flow_path: str | None, flow_yaml: str | None
) -> None:
    with pytest.raises(Exception, match="exactly one"):
        _resolve(flow_path, flow_yaml)


# --- running ---


def test_run_cli_flow_runs_inline_text_without_touching_disk(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)

    result = run_cli_flow(session, _cli_flow(None, FLOW_YAML), {}, from_step=None)

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


def test_run_command_runs_a_flow_file_with_a_sibling_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The child resolves against the parent's directory, not the CWD."""
    (tmp_path / "child.yaml").write_text(CHILD_YAML)
    parent = tmp_path / "parent.yaml"
    parent.write_text(PARENT_YAML)
    session = _mock_session(tmp_path)
    monkeypatch.setattr("llm_browser.cli.build_session", lambda **kwargs: session)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = CliRunner().invoke(main, ["run", "--flow", str(parent)])

    assert result.exit_code == 0
    assert session.goto.call_args.args == ("https://child.example",)


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


def test_validate_counts_a_sibling_child_of_a_flow_file(tmp_path: Path) -> None:
    (tmp_path / "child.yaml").write_text(CHILD_YAML)
    parent = tmp_path / "parent.yaml"
    parent.write_text(PARENT_YAML)

    result = CliRunner().invoke(main, ["validate", "--flow", str(parent)])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["subflow_count"] == 1


def test_validate_reports_a_parse_error_with_the_format() -> None:
    result = CliRunner().invoke(main, ["validate", "--flow-yaml", "steps: [\n - a\n"])
    assert result.exit_code == 1
    assert "invalid flow yaml" in json.loads(result.stderr)["message"]


def test_validate_reports_a_missing_flow_file(tmp_path: Path) -> None:
    result = CliRunner().invoke(main, ["validate", "--flow", str(tmp_path / "no.yaml")])
    assert result.exit_code == 1
    assert json.loads(result.stderr)["error"] == "FlowNotFoundError"


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

    result = run_cli_flow(
        session,
        _cli_flow(str(path)),
        {},
        from_step=None,
        flow_path=file_path(str(path)),
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

    result = run_cli_flow(session, _cli_flow(None, PARENT_YAML), {}, from_step=None)

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
