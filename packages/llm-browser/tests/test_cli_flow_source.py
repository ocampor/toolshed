"""Tests for the CLI's flow sources: --flow PATH, --flow -, --flow-yaml."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml
from click.testing import CliRunner

from llm_browser.cli import flow_yaml_text, main, run_cli_flow
from llm_browser.models import FlowSuccess
from llm_browser.session import BrowserSession

FLOW_YAML = yaml.dump(
    {"steps": [{"name": "s1", "action": "goto", "url": "https://example.com"}]}
)


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


@pytest.mark.parametrize(
    ("flow_path", "flow_yaml", "expected"),
    [
        ("flow.yml", None, None),
        (None, FLOW_YAML, FLOW_YAML),
    ],
)
def test_flow_yaml_text_picks_the_source(
    flow_path: str | None, flow_yaml: str | None, expected: str | None
) -> None:
    assert flow_yaml_text(flow_path, flow_yaml) == expected


@pytest.mark.parametrize(
    ("flow_path", "flow_yaml"),
    [(None, None), ("flow.yml", FLOW_YAML)],
)
def test_flow_yaml_text_requires_exactly_one_source(
    flow_path: str | None, flow_yaml: str | None
) -> None:
    with pytest.raises(Exception, match="exactly one"):
        flow_yaml_text(flow_path, flow_yaml)


# --- running ---


def test_run_cli_flow_runs_yaml_text_without_touching_disk(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    result = run_cli_flow(session, "", FLOW_YAML, {}, selector_map=None, from_step=None)
    assert isinstance(result, FlowSuccess)
    assert session.goto.call_args.args == ("https://example.com",)


def test_run_cli_flow_delegates_to_run_flow_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake_run_flow_file(session: Any, path: str, data: Any, **kwargs: Any) -> str:
        seen["path"] = path
        return "ran"

    monkeypatch.setattr("llm_browser.cli.run_flow_file", fake_run_flow_file)
    result = run_cli_flow(
        _mock_session(tmp_path),
        "flow.yml",
        None,
        {},
        selector_map=None,
        from_step=None,
    )
    assert (result, seen["path"]) == ("ran", "flow.yml")


# --- validate ---


def test_validate_accepts_inline_yaml() -> None:
    result = CliRunner().invoke(main, ["validate", "--flow-yaml", FLOW_YAML])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "ok": True,
        "flow": "<inline>",
        "step_count": 1,
        "subflow_count": 0,
    }


def test_validate_reads_stdin() -> None:
    result = CliRunner().invoke(main, ["validate", "--flow", "-"], input=FLOW_YAML)
    assert result.exit_code == 0
    assert json.loads(result.stdout)["flow"] == "<inline>"


def test_validate_rejects_two_sources() -> None:
    result = CliRunner().invoke(
        main, ["validate", "--flow", "f.yml", "--flow-yaml", FLOW_YAML]
    )
    assert result.exit_code == 2
    assert "exactly one" in result.output
