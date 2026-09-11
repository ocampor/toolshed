"""Tests for BrowserSession state file lifecycle."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from llm_browser.chrome import is_process_alive
from llm_browser.drivers.base import Driver
from llm_browser.models import SessionInfo
from llm_browser.session import BrowserSession


def test_save_and_load_state(tmp_path: Path) -> None:
    session = BrowserSession(state_dir=tmp_path)
    info = SessionInfo(
        pid=9999, cdp_url="ws://127.0.0.1:9222/devtools", user_data_dir="/tmp/ud"
    )
    session._ensure_dirs()
    session.state.save(info)

    loaded = session.state.load()
    assert loaded is not None
    assert loaded.pid == 9999
    assert loaded.cdp_url == "ws://127.0.0.1:9222/devtools"


def test_load_state_missing(tmp_path: Path) -> None:
    session = BrowserSession(state_dir=tmp_path)
    assert session.state.load() is None


def test_clear_state(tmp_path: Path) -> None:
    session = BrowserSession(state_dir=tmp_path)
    info = SessionInfo(pid=9999, cdp_url="ws://localhost:9222", user_data_dir="/tmp/ud")
    session._ensure_dirs()
    session.state.save(info)
    assert session.state.load() is not None

    session.state.clear()
    assert session.state.load() is None


def test_clear_state_noop_when_missing(tmp_path: Path) -> None:
    session = BrowserSession(state_dir=tmp_path)
    session.state.clear()  # should not raise


def test_status_closed_no_state(tmp_path: Path) -> None:
    session = BrowserSession(state_dir=tmp_path)
    result = session.status()
    assert result.status == "closed"
    assert result.cdp_url is None


def test_session_dir_uses_session_id(tmp_path: Path) -> None:
    session = BrowserSession(session_id="sat", state_dir=tmp_path)
    assert session.session_dir == tmp_path / "sessions" / "sat"


def test_default_session_id(tmp_path: Path) -> None:
    session = BrowserSession(state_dir=tmp_path)
    assert session.session_dir == tmp_path / "sessions" / "default"


def testis_process_alive_current_pid() -> None:
    import os

    assert is_process_alive(os.getpid()) is True


def testis_process_alive_nonexistent() -> None:
    # PID 2^30 is extremely unlikely to exist
    assert is_process_alive(1 << 30) is False


# --- executable_path ---


def test_executable_path_threaded_to_driver(tmp_path: Path) -> None:
    from tests.test_attach import AttachStubDriver

    from llm_browser.drivers.base import DriverHandle

    driver = AttachStubDriver()
    captured: dict[str, object] = {}

    def capturing_launch(
        user_data_dir: Path,
        url: str | None,
        headed: bool,
        executable_path: str | None = None,
    ) -> DriverHandle:
        captured["executable_path"] = executable_path
        return DriverHandle(driver=driver.name, user_data_dir=str(user_data_dir), pid=1)

    driver.launch = capturing_launch  # type: ignore[method-assign]
    session = BrowserSession(
        state_dir=tmp_path,
        driver=driver,
        executable_path="/usr/bin/chromium",
    )
    session.launch(url=None, headed=False)
    assert captured["executable_path"] == "/usr/bin/chromium"


# --- element_exists ---


def _session_with_mock_driver(tmp_path: Path) -> BrowserSession:
    session = BrowserSession(state_dir=tmp_path)
    session.driver = MagicMock()
    session._page = MagicMock()
    return session


def test_element_exists_is_true_once_the_element_attaches(tmp_path: Path) -> None:
    session = _session_with_mock_driver(tmp_path)
    session.driver.count.return_value = 1
    assert session.element_exists("#out") is True


def test_element_exists_is_false_when_nothing_ever_matches(tmp_path: Path) -> None:
    session = _session_with_mock_driver(tmp_path)
    session.driver.count.return_value = 0
    assert session.element_exists("#out", timeout=0) is False


def test_element_exists_propagates_a_driver_error(tmp_path: Path) -> None:
    """A CDP failure is not "not yet": only a timeout reads as False."""
    session = _session_with_mock_driver(tmp_path)
    session.driver.count.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        session.element_exists("#out")


def test_screenshot_bytes_returns_driver_bytes(tmp_path: Path) -> None:
    driver = MagicMock(spec=Driver)
    driver.screenshot_bytes.return_value = b"png-bytes"
    session = BrowserSession(state_dir=tmp_path, driver=driver)
    session._page = MagicMock()

    assert session.screenshot_bytes() == b"png-bytes"
    driver.screenshot_bytes.assert_called_once_with(session._page)


def test_screenshot_bytes_writes_nothing_to_session_dir(tmp_path: Path) -> None:
    driver = MagicMock(spec=Driver)
    driver.screenshot_bytes.return_value = b"png-bytes"
    session = BrowserSession(state_dir=tmp_path, driver=driver)
    session._page = MagicMock()

    session.screenshot_bytes()
    assert not session.session_dir.exists()
