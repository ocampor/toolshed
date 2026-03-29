"""Tests for BrowserSession state file lifecycle."""

from pathlib import Path

from llm_browser.chrome import is_process_alive
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
