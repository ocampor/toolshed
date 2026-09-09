"""Tests for BrowserSession state file lifecycle."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from llm_browser.chrome import is_process_alive
from llm_browser.constants import DEFAULT_WAIT_TIMEOUT_MS
from llm_browser.drivers.base import Driver
from llm_browser.models import SessionInfo
from llm_browser.session import BrowserSession


def test_save_and_load_state(tmp_path: Path) -> None:
    session = BrowserSession(state_dir=tmp_path)
    info = SessionInfo(
        pid=9999, cdp_url="ws://127.0.0.1:9222/devtools", user_data_dir="/tmp/ud"
    )
    session._ensure_dirs()
    session._save_state(info)

    loaded = session._load_state()
    assert loaded is not None
    assert loaded.pid == 9999
    assert loaded.cdp_url == "ws://127.0.0.1:9222/devtools"


def test_load_state_missing(tmp_path: Path) -> None:
    session = BrowserSession(state_dir=tmp_path)
    assert session._load_state() is None


def test_clear_state(tmp_path: Path) -> None:
    session = BrowserSession(state_dir=tmp_path)
    info = SessionInfo(pid=9999, cdp_url="ws://localhost:9222", user_data_dir="/tmp/ud")
    session._ensure_dirs()
    session._save_state(info)
    assert session._load_state() is not None

    session._clear_state()
    assert session._load_state() is None


def test_clear_state_noop_when_missing(tmp_path: Path) -> None:
    session = BrowserSession(state_dir=tmp_path)
    session._clear_state()  # should not raise


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


# --- wait_until_stable ---


def _session_with_evaluate(tmp_path: Path, result: object) -> BrowserSession:
    s = BrowserSession(state_dir=tmp_path)
    page = MagicMock()
    locator = MagicMock()
    locator.count.return_value = 1
    locator.first.evaluate.return_value = result
    page.locator.return_value = locator
    s._page = page
    return s


def test_wait_until_stable_returns_text(tmp_path: Path) -> None:
    session = _session_with_evaluate(tmp_path, "final reply")
    assert session.wait_until_stable("#out") == "final reply"


def test_wait_until_stable_times_out(tmp_path: Path) -> None:
    # In-page script resolves to null on timeout; driver maps that to None.
    session = _session_with_evaluate(tmp_path, None)
    with pytest.raises(TimeoutError):
        session.wait_until_stable("#out", timeout_s=0.01)


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


# --- wait_for / element_exists ---


def _session_with_mock_driver(tmp_path: Path) -> BrowserSession:
    session = BrowserSession(state_dir=tmp_path)
    session.driver = MagicMock()
    session._page = MagicMock()
    return session


@pytest.mark.parametrize("state", ["attached", "detached", "visible", "hidden"])
def test_wait_for_passes_state_to_driver(tmp_path: Path, state: str) -> None:
    session = _session_with_mock_driver(tmp_path)
    assert session.wait_for("#out", state, timeout=123) is True
    _, args, _ = session.driver.wait_for_state.mock_calls[0]
    assert args[1:] == (state, 123)


def test_wait_for_defaults_to_attached_and_default_timeout(tmp_path: Path) -> None:
    session = _session_with_mock_driver(tmp_path)
    session.wait_for("#out")
    _, args, _ = session.driver.wait_for_state.mock_calls[0]
    assert args[1:] == ("attached", DEFAULT_WAIT_TIMEOUT_MS)


class _DriverTimeoutError(Exception):
    """Stands in for patchright's TimeoutError, which is not the builtin."""


_DriverTimeoutError.__name__ = "TimeoutError"


@pytest.mark.parametrize("exc", [TimeoutError("nope"), _DriverTimeoutError("nope")])
def test_wait_for_returns_false_on_timeout(tmp_path: Path, exc: Exception) -> None:
    session = _session_with_mock_driver(tmp_path)
    session.driver.wait_for_state.side_effect = exc
    assert session.wait_for("#out", "visible") is False


def test_wait_for_propagates_non_timeout_errors(tmp_path: Path) -> None:
    session = _session_with_mock_driver(tmp_path)
    session.driver.wait_for_state.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        session.wait_for("#out")


@pytest.mark.parametrize(
    "side_effect,expected",
    [(None, True), (TimeoutError("nope"), False), (_DriverTimeoutError("nope"), False)],
)
def test_element_exists_routes_through_wait_for(
    tmp_path: Path, side_effect: Exception | None, expected: bool
) -> None:
    session = _session_with_mock_driver(tmp_path)
    session.driver.wait_for_state.side_effect = side_effect
    assert session.element_exists("#out") is expected
    _, args, _ = session.driver.wait_for_state.mock_calls[0]
    assert args[1:] == ("attached", DEFAULT_WAIT_TIMEOUT_MS)


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
    assert not session._screenshot_path.exists()
