"""`goto`, `launch` and `launch_detached` refuse non-http(s) schemes."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from llm_browser.drivers import DriverHandle
from llm_browser.models import FlowData, FlowError, GotoStep
from llm_browser.session import BrowserSession
from llm_browser.steps import execute_step


def _session(tmp_path: Path) -> BrowserSession:
    session = BrowserSession(state_dir=tmp_path)
    session.driver = MagicMock()
    # A real Driver's `name` is a plain string; the pre-attach SessionInfo
    # `launch_detached` writes validates it as one.
    session.driver.name = "mock"
    session._page = MagicMock()
    handle = DriverHandle(
        driver="mock", pid=1, endpoint="http://cdp", user_data_dir="d"
    )
    session.driver.launch.return_value = handle
    session.driver.attach.return_value = handle
    session.driver.page_url.return_value = None
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


BAD_URLS = [
    "file:///etc/passwd",
    "chrome://settings",
    "javascript:alert(1)",
    "view-source:http://x",
    "some/page.html",
]


@pytest.mark.parametrize("url", BAD_URLS)
def test_launch_rejects_non_http_schemes(tmp_path: Path, url: str) -> None:
    session = _session(tmp_path)
    with pytest.raises(ValueError, match="url must be http or https"):
        session.launch(url)
    session.driver.launch.assert_not_called()


def test_launch_allows_no_url(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.launch()
    session.driver.launch.assert_called_once()


@pytest.mark.parametrize("url", BAD_URLS)
def test_launch_detached_rejects_non_http_schemes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    spawn = MagicMock()
    monkeypatch.setattr("llm_browser.session.spawn_detached_chromium", spawn)
    session = _session(tmp_path)
    with pytest.raises(ValueError, match="url must be http or https"):
        session.launch_detached(url)
    spawn.assert_not_called()


def test_launch_detached_allows_no_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "llm_browser.session.spawn_detached_chromium",
        lambda *a, **k: (123, "http://127.0.0.1:9222"),
    )
    session = _session(tmp_path)
    session.launch_detached()
    session.driver.goto.assert_not_called()
