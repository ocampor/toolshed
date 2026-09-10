"""Which drivers can run here, and how to get a headless session for one.

A driver that is not installed, or that needs a browser binary this machine
does not have, is a *skip* with a reason — never a silent omission and never a
failure. The point of the suite is an honest table.
"""

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from llm_browser.drivers import Driver, get_registry
from llm_browser.session import BrowserSession

CONFORMANCE_DRIVERS = ("patchright", "camoufox", "nodriver")

# nodriver drives a real Chrome over CDP and ships no browser of its own.
CHROME_BINARIES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
)


def installed_drivers() -> list[str]:
    registry = get_registry()
    return [name for name in CONFORMANCE_DRIVERS if name in registry]


def chrome_binary() -> str | None:
    for name in CHROME_BINARIES:
        found = shutil.which(name)
        if found:
            return found
    return None


def unavailable(driver: str) -> str | None:
    """Why ``driver`` cannot run here, or ``None`` if it can."""
    if driver not in get_registry():
        return f"extra not installed (uv sync --extra {driver})"
    if driver == "nodriver" and chrome_binary() is None:
        return f"no Chrome/Chromium on PATH (looked for {', '.join(CHROME_BINARIES)})"
    return None


def configured(driver: str) -> Driver | str:
    """The driver as the suite runs it.

    camoufox is built with ``humanize=False``. Its humanized cursor
    intermittently leaves a Playwright ``click`` waiting out the whole 30s
    action timeout on a target it has already declared visible, enabled and
    stable — a Camoufox cursor problem, not an llm-browser contract question,
    and one flaky scenario poisons every answer in the column.
    """
    if driver != "camoufox":
        return driver
    from llm_browser.drivers.camoufox import CamoufoxDriver

    return CamoufoxDriver(humanize=False)


@contextmanager
def launched_session(driver: str) -> Iterator[BrowserSession]:
    """One headless browser, on a throwaway profile, closed on the way out."""
    with tempfile.TemporaryDirectory(prefix="llm-browser-conformance-") as state_dir:
        session = BrowserSession(
            session_id=f"conformance-{driver}",
            state_dir=Path(state_dir),
            # Both artifacts, so the flow checks can assert screenshot AND dom.
            capture="both",
            driver=configured(driver),
            executable_path=chrome_binary() if driver == "nodriver" else None,
        )
        session.launch(headed=False)
        try:
            yield session
        finally:
            session.close()
