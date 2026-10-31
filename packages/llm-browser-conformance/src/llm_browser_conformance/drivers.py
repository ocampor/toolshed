"""A driver missing here is a skip with a reason, never an omission or a failure."""

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from llm_browser.drivers import Driver, get_registry
from llm_browser.session import BrowserSession

from llm_browser_conformance.interrupts import (
    install_interrupt_handlers,
    register_launch_placeholder,
    register_session,
    unregister_launch_placeholder,
    unregister_session,
)

CONFORMANCE_DRIVERS = ("patchright", "camoufox", "nodriver")

# Playwright's own action timeout, which no llm-browser step timeout reaches
# (see `native select disabled option`). Left at its 30s default it would cost
# the suite a minute per run to demonstrate one gap; 5s is still far outside
# every step budget the fixtures declare, so the gap still shows.
PLAYWRIGHT_ACTION_TIMEOUT_MS = 5_000

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
    if driver not in get_registry():
        return f"extra not installed (uv sync --extra {driver})"
    if driver == "nodriver" and chrome_binary() is None:
        return f"no Chrome/Chromium on PATH (looked for {', '.join(CHROME_BINARIES)})"
    return None


def configured(driver: str) -> Driver | str:
    """camoufox runs with ``humanize=False``: its cursor intermittently stalls a Playwright ``click``
    to timeout. The README links here.
    """
    if driver != "camoufox":
        return driver
    from llm_browser.drivers.camoufox import CamoufoxDriver

    return CamoufoxDriver(humanize=False)


def bound_action_timeout(session: BrowserSession, driver: str) -> None:
    """The step budget never reaches ``Driver.select_option``, so cap Playwright's own default;
    5s still exceeds every fixture budget.
    """
    if driver == "nodriver":
        return
    session.get_page().context.set_default_timeout(PLAYWRIGHT_ACTION_TIMEOUT_MS)


@contextmanager
def launched_session(driver: str, headed: bool = False) -> Iterator[BrowserSession]:
    """``ignore_cleanup_errors``: Chromium still flushes the profile after ``close()``, racing ``rmdir``.
    Also registered with ``interrupts``: a killed worker never reaches the ``finally``.
    """
    install_interrupt_handlers()
    placeholder = register_launch_placeholder()
    with tempfile.TemporaryDirectory(
        prefix="llm-browser-conformance-", ignore_cleanup_errors=True
    ) as state_dir:
        session = BrowserSession(
            session_id=f"conformance-{driver}",
            state_dir=Path(state_dir),
            capture="both",
            driver=configured(driver),
            executable_path=chrome_binary() if driver == "nodriver" else None,
        )
        try:
            session.launch(headed=headed)
        except BaseException:
            unregister_launch_placeholder(placeholder)
            raise
        bound_action_timeout(session, driver)
        register_session(session)
        unregister_launch_placeholder(placeholder)
        try:
            yield session
        finally:
            unregister_session(session)
            session.close()
