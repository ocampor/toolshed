"""Chromium binary discovery and detached-launch helpers."""

import os
import signal
import subprocess
import time
from pathlib import Path

from patchright.sync_api import sync_playwright


class ChromiumNotInstalledError(RuntimeError):
    """Raised when Playwright's bundled Chromium is missing."""


def chromium_executable() -> str:
    """Get Chromium binary path from Playwright installation.

    Raises ChromiumNotInstalledError with an actionable remediation message
    if the binary is missing.
    """
    try:
        pw = sync_playwright().start()
        try:
            path = pw.chromium.executable_path
        finally:
            pw.stop()
    except Exception as e:
        raise ChromiumNotInstalledError(
            "Chromium binary not found. Run: "
            "`uv run patchright install chromium` "
            "(or `patchright install chromium` without uv). "
            "Alternatively pass `executable_path=` to BrowserSession."
        ) from e
    if not path or not Path(path).exists():
        raise ChromiumNotInstalledError(
            f"Chromium binary path {path!r} does not exist. Run: "
            "`uv run patchright install chromium` "
            "(or `patchright install chromium` without uv). "
            "Alternatively pass `executable_path=` to BrowserSession."
        )
    return path


def is_process_alive(pid: int) -> bool:
    """Check if a process with given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def spawn_detached_chromium(
    user_data_dir: Path,
    headed: bool,
    executable_path: str | None = None,
    startup_timeout_s: float = 20.0,
) -> tuple[int, str]:
    """Spawn a Chromium that outlives the Python process. Returns (pid, cdp_url).

    Uses ``--remote-debugging-port=0`` + the ``DevToolsActivePort`` file Chromium
    writes into ``user_data_dir`` on startup to discover the chosen port.
    The child is placed in a new session (``setsid``) so it survives parent
    exit and CLI re-invocations can reconnect over CDP.

    Note: running this Chromium via ``connect_over_cdp`` does NOT activate
    patchright's stealth patches. Value comes from reusing a *warmed* profile
    across CLI calls — log in / pass Cloudflare once, reuse forever.
    """
    user_data_dir.mkdir(parents=True, exist_ok=True)
    port_file = user_data_dir / "DevToolsActivePort"
    if port_file.exists():
        port_file.unlink()  # stale from a prior run

    binary = executable_path or chromium_executable()
    args = [
        binary,
        f"--user-data-dir={user_data_dir}",
        "--remote-debugging-port=0",
        "--no-first-run",
        "--no-default-browser-check",
        # Hide navigator.webdriver=true, which Chromium sets as soon as a
        # CDP client attaches. Without this, browserscan/sannysoft flag
        # the session even when the profile and binary are fully real.
        "--disable-blink-features=AutomationControlled",
    ]
    if not headed:
        args.append("--headless=new")

    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    cdp_url = _wait_for_devtools_port(port_file, proc, startup_timeout_s)
    return proc.pid, cdp_url


def _wait_for_devtools_port(
    port_file: Path, proc: subprocess.Popen[bytes], timeout_s: float
) -> str:
    """Poll DevToolsActivePort until Chromium writes a port, or give up."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"Chromium exited with code {proc.returncode} before writing "
                "DevToolsActivePort. Check that the binary runs standalone."
            )
        if port_file.exists():
            first_line = port_file.read_text().splitlines()[0].strip()
            if first_line.isdigit():
                return f"http://127.0.0.1:{first_line}"
        time.sleep(0.1)
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except OSError:
        pass
    raise TimeoutError(
        f"Chromium did not open CDP within {timeout_s}s (no DevToolsActivePort)."
    )


def kill_detached_chromium(pid: int) -> None:
    """Terminate a detached Chromium (and its process group) by PID."""
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except OSError:
        pass
