"""The URL-taking CLI commands report a rejected scheme as a click usage error."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from llm_browser.cli import main
from llm_browser.session import BrowserSession


@pytest.fixture
def cli_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BrowserSession:
    """A real session — a MagicMock one would never reach the scheme guard."""
    session = BrowserSession(state_dir=tmp_path)
    session.driver = MagicMock()
    session._page = MagicMock()
    session.driver.page_url.return_value = "https://example.com"
    monkeypatch.setattr("llm_browser.cli.build_session", lambda **kwargs: session)
    return session


@pytest.mark.parametrize("command", ["goto", "open", "daemon"])
def test_a_rejected_scheme_is_a_usage_error_without_a_traceback(
    cli_session: BrowserSession, command: str
) -> None:
    result = CliRunner().invoke(main, [command, "--url", "file:///x"])

    output = result.output + result.stderr
    assert result.exit_code == 2
    assert "url must be http or https: file:///x" in output
    assert "Traceback" not in output
    assert isinstance(result.exception, SystemExit)
    cli_session.driver.goto.assert_not_called()
    cli_session.driver.launch.assert_not_called()


def test_goto_navigates_for_an_http_url(cli_session: BrowserSession) -> None:
    result = CliRunner().invoke(main, ["goto", "--url", "https://example.com"])

    assert result.exit_code == 0
    _, args, _ = cli_session.driver.goto.mock_calls[0]
    assert args[1] == "https://example.com"
