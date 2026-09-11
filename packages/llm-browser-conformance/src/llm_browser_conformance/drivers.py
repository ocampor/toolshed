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

from llm_browser_conformance.interrupts import (
    install_interrupt_handlers,
    register_session,
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
    """Why ``driver`` cannot run here, or ``None`` if it can."""
    if driver not in get_registry():
        return f"extra not installed (uv sync --extra {driver})"
    if driver == "nodriver" and chrome_binary() is None:
        return f"no Chrome/Chromium on PATH (looked for {', '.join(CHROME_BINARIES)})"
    return None


def configured(driver: str) -> Driver | str:
    """The driver as the suite runs it.

    camoufox is built with ``humanize=False``. Its humanized cursor
    intermittently leaves a Playwright ``click`` waiting out the whole action
    timeout on a target it has already declared visible, enabled and stable —
    a Camoufox cursor problem, not an llm-browser contract question, and one
    flaky scenario poisons every answer in the column. This is the one home
    for that decision; the README links here.
    """
    if driver != "camoufox":
        return driver
    from llm_browser.drivers.camoufox import CamoufoxDriver

    return CamoufoxDriver(humanize=False)


def bound_action_timeout(session: BrowserSession, driver: str) -> None:
    """Cap what Playwright will wait for one action.

    Not a workaround: the step budget a flow declares never reaches
    ``Driver.select_option`` (it bounds ``find`` only), so a Playwright driver
    falls back to its own default. Capping it keeps the run short without
    hiding the gap — 5s is still well past any budget the fixtures ask for.
    """
    if driver == "nodriver":
        return
    session.get_page().context.set_default_timeout(PLAYWRIGHT_ACTION_TIMEOUT_MS)


@contextmanager
def launched_session(driver: str) -> Iterator[BrowserSession]:
    """One headless browser, on a throwaway profile, closed on the way out.

    ``ignore_cleanup_errors`` narrowly covers the profile directory, not the
    session: ``close()`` releases the connection and returns, but Chromium is
    still flushing its profile for a moment afterwards, so the ``rmdir`` races
    it and raises ``Directory not empty``. That is the OS reclaiming a
    throwaway directory, not a browser refusing to stop — and charging it to
    the teardown row would report a driver failure that did not happen. A
    ``close()`` that really does raise still reaches the ``finally`` below.

    A worker killed or timed out mid-run never reaches that ``finally`` at
    all, so the session also registers with ``interrupts`` for the
    ``atexit``/SIGINT/SIGTERM sweep to close on its way out.
    """
    install_interrupt_handlers()
    with tempfile.TemporaryDirectory(
        prefix="llm-browser-conformance-", ignore_cleanup_errors=True
    ) as state_dir:
        session = BrowserSession(
            session_id=f"conformance-{driver}",
            state_dir=Path(state_dir),
            # Both artifacts, so the flow checks can assert screenshot AND dom.
            capture="both",
            driver=configured(driver),
            executable_path=chrome_binary() if driver == "nodriver" else None,
        )
        session.launch(headed=False)
        bound_action_timeout(session, driver)
        register_session(session)
        try:
            yield session
        finally:
            unregister_session(session)
            session.close()
