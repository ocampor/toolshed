"""`BrowserSession.goto` refuses non-http(s) schemes, and flows inherit that."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from llm_browser.models import FlowData, FlowError, GotoStep
from llm_browser.session import BrowserSession
from llm_browser.steps import execute_step


def _session(tmp_path: Path) -> BrowserSession:
    session = BrowserSession(state_dir=tmp_path)
    session.driver = MagicMock()
    session._page = MagicMock()
    return session


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "chrome://settings",
        "javascript:alert(1)",
        "view-source:http://x",
        "some/page.html",
    ],
)
def test_goto_rejects_non_http_schemes(tmp_path: Path, url: str) -> None:
    session = _session(tmp_path)
    with pytest.raises(ValueError, match="url must be http or https"):
        session.goto(url)
    session.driver.goto.assert_not_called()


@pytest.mark.parametrize("url", ["http://example.com", "https://example.com"])
def test_goto_allows_http_schemes(tmp_path: Path, url: str) -> None:
    session = _session(tmp_path)
    session.goto(url)
    _, args, _ = session.driver.goto.mock_calls[0]
    assert args[1:] == (url, "domcontentloaded")


def test_goto_honors_explicit_allowed_schemes(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.goto("file:///tmp/x.html", allowed_schemes=("file",))
    _, args, _ = session.driver.goto.mock_calls[0]
    assert args[1] == "file:///tmp/x.html"


def test_flow_goto_to_file_scheme_is_a_step_failure(tmp_path: Path) -> None:
    """A real session — a MagicMock one would never reach the guard."""
    session = _session(tmp_path)
    step = GotoStep(action="goto", name="open", url="file:///etc/passwd")

    result = execute_step(session, step, FlowData())

    assert isinstance(result, FlowError)
    assert result.step == "open"
    assert result.data.error == "ValueError"
    assert "url must be http or https" in result.data.message
    session.driver.goto.assert_not_called()
