"""Chrome process lifecycle: launch, detect CDP URL, kill."""

import os
import signal
import subprocess
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from llm_browser.constants import CDP_STARTUP_TIMEOUT, CDP_URL_RE


def chromium_executable() -> str:
    """Get Chromium binary path from Playwright installation."""
    pw = sync_playwright().start()
    try:
        return pw.chromium.executable_path
    finally:
        pw.stop()


def launch_chrome(
    user_data_dir: Path,
    url: str | None = None,
    headed: bool = True,
) -> tuple[int, str]:
    """Launch Chrome as a detached background process.

    Returns (pid, cdp_url).
    """
    args = [
        chromium_executable(),
        "--remote-debugging-port=0",
        f"--user-data-dir={user_data_dir}",
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if not headed:
        args.append("--headless=new")
    if url:
        args.append(url)

    process = subprocess.Popen(
        args,
        stderr=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        start_new_session=True,
    )

    cdp_url = _wait_for_cdp_url(process)
    return process.pid, cdp_url


def _wait_for_cdp_url(process: subprocess.Popen[bytes]) -> str:
    """Read Chrome stderr until the CDP websocket URL appears."""
    assert process.stderr is not None
    deadline = time.monotonic() + CDP_STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        line = process.stderr.readline().decode(errors="replace")
        match = CDP_URL_RE.search(line)
        if match:
            return match.group(1)
    raise TimeoutError("Chrome did not emit CDP URL within timeout")


def is_process_alive(pid: int) -> bool:
    """Check if a process with given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def kill_chrome(pid: int) -> None:
    """Send SIGTERM to a Chrome process if alive."""
    if is_process_alive(pid):
        os.kill(pid, signal.SIGTERM)
