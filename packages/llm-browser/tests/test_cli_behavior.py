"""`llm-browser run --behavior`: one run's humanization, named in the result."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from click.testing import CliRunner

from llm_browser.behavior import Behavior
from llm_browser.cli import main, resolve_behavior
from llm_browser.session import BrowserSession
from tests.flow_helpers import stub_matching

CLICK_FLOW = yaml.dump(
    {"steps": [{"name": "s1", "action": "click", "selector": "#btn"}]}
)


@pytest.fixture
def session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock = stub_matching(MagicMock(spec=BrowserSession))
    mock.session_dir = tmp_path
    mock.behavior = Behavior.human()
    mock.capture = "screenshot"
    mock.click.return_value = None
    monkeypatch.setattr("llm_browser.cli.build_session", lambda **kwargs: mock)
    return mock


def run_cli(tmp_path: Path, *args: str) -> tuple[int, dict[str, object]]:
    path = tmp_path / "flow.yaml"
    path.write_text(CLICK_FLOW)
    result = CliRunner().invoke(main, ["run", "--flow", str(path), *args])
    return result.exit_code, json.loads(result.stdout or "{}")


def test_behavior_off_takes_the_plain_path_on_a_human_session(
    tmp_path: Path, session: MagicMock
) -> None:
    exit_code, payload = run_cli(tmp_path, "--behavior", "off")

    assert exit_code == 0
    assert session.click.call_args.kwargs["behavior"] == Behavior.off()
    assert payload["behavior"] == "off"
    assert session.behavior == Behavior.human()


def test_without_the_option_the_run_is_the_sessions_own_behavior(
    tmp_path: Path, session: MagicMock
) -> None:
    exit_code, payload = run_cli(tmp_path)

    assert exit_code == 0
    assert session.click.call_args.kwargs["behavior"] == Behavior.human()
    assert payload["behavior"] == "human"


def test_a_yaml_path_loads_that_config(tmp_path: Path) -> None:
    config = tmp_path / "behavior.yaml"
    config.write_text(yaml.dump({"min_gap_ms": 1_500}))

    loaded = resolve_behavior(str(config))

    assert loaded is not None
    assert loaded.min_gap_ms == 1_500


def test_a_missing_path_is_a_usage_error(tmp_path: Path, session: MagicMock) -> None:
    exit_code, _ = run_cli(tmp_path, "--behavior", str(tmp_path / "nope.yaml"))

    assert exit_code != 0


def test_a_malformed_yaml_is_a_usage_error(tmp_path: Path, session: MagicMock) -> None:
    """A syntax error in the file is the user's typo, not a traceback."""
    config = tmp_path / "behavior.yaml"
    config.write_text("min_gap_ms: [unclosed\n")

    exit_code, _ = run_cli(tmp_path, "--behavior", str(config))

    assert exit_code != 0
