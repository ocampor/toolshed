"""Tests for detached-Chromium spawn + BrowserSession.launch_detached."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from llm_browser import chrome as chrome_mod
from llm_browser.session import BrowserSession
from tests.test_attach import AttachStubDriver


def test_spawn_detached_reads_port_from_devtools_file(tmp_path: Path) -> None:
    fake_proc = MagicMock()
    fake_proc.pid = 4242
    fake_proc.poll.return_value = None

    def fake_popen(*args: Any, **kwargs: Any) -> MagicMock:
        (tmp_path / "DevToolsActivePort").write_text("54321\n/devtools/browser/xyz\n")
        return fake_proc

    with (
        patch.object(chrome_mod, "chromium_executable", return_value="/fake/chromium"),
        patch("llm_browser.chrome.subprocess.Popen", side_effect=fake_popen),
    ):
        pid, cdp = chrome_mod.spawn_detached_chromium(tmp_path, headed=True)

    assert pid == 4242
    assert cdp == "http://127.0.0.1:54321"


def test_spawn_detached_raises_when_chromium_exits_early(tmp_path: Path) -> None:
    fake_proc = MagicMock()
    fake_proc.pid = 1
    fake_proc.poll.return_value = 127
    fake_proc.returncode = 127
    with (
        patch.object(chrome_mod, "chromium_executable", return_value="/fake/chromium"),
        patch("llm_browser.chrome.subprocess.Popen", return_value=fake_proc),
    ):
        with pytest.raises(RuntimeError, match="exited with code 127"):
            chrome_mod.spawn_detached_chromium(tmp_path, headed=True)


def test_spawn_detached_times_out_when_port_never_appears(tmp_path: Path) -> None:
    fake_proc = MagicMock()
    fake_proc.pid = 1
    fake_proc.poll.return_value = None
    with (
        patch.object(chrome_mod, "chromium_executable", return_value="/fake/chromium"),
        patch("llm_browser.chrome.subprocess.Popen", return_value=fake_proc),
        patch("llm_browser.chrome.os.getpgid", return_value=1),
        patch("llm_browser.chrome.os.killpg"),
    ):
        with pytest.raises(TimeoutError, match="did not open CDP"):
            chrome_mod.spawn_detached_chromium(
                tmp_path, headed=True, startup_timeout_s=0.05
            )


def test_launch_detached_persists_pid_and_attaches(tmp_path: Path) -> None:
    driver = AttachStubDriver()
    session = BrowserSession(state_dir=tmp_path, driver=driver)
    with patch(
        "llm_browser.session.spawn_detached_chromium",
        return_value=(9999, "http://127.0.0.1:54321"),
    ):
        result = session.launch_detached(headed=True)

    assert result.cdp_url == "http://127.0.0.1:54321"
    info = session._load_state()
    assert info is not None
    assert info.mode == "attached"
    assert info.pid == 9999
    assert info.cdp_url == "http://127.0.0.1:54321"
    assert driver.attach_calls == ["http://127.0.0.1:54321"]


def test_stop_detached_kills_pid_and_clears_state(tmp_path: Path) -> None:
    driver = AttachStubDriver()
    session = BrowserSession(state_dir=tmp_path, driver=driver)
    with patch(
        "llm_browser.session.spawn_detached_chromium",
        return_value=(9999, "http://127.0.0.1:54321"),
    ):
        session.launch_detached()

    with patch("llm_browser.session.kill_detached_chromium") as kill:
        session.stop_detached()
        kill.assert_called_once_with(9999)

    assert session._load_state() is None
    assert len(driver.close_calls) == 1


def test_close_does_not_kill_detached_pid(tmp_path: Path) -> None:
    """Plain close() leaves the detached browser alive — only stop_detached kills."""
    driver = AttachStubDriver()
    session = BrowserSession(state_dir=tmp_path, driver=driver)
    with patch(
        "llm_browser.session.spawn_detached_chromium",
        return_value=(9999, "http://127.0.0.1:54321"),
    ):
        session.launch_detached()

    with patch("llm_browser.session.kill_detached_chromium") as kill:
        session.close()
        kill.assert_not_called()
