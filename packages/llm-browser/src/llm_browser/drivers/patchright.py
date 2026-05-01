"""Patchright driver: in-process Chromium via launch_persistent_context.

Patchright's stealth patches (navigator.webdriver, chrome runtime, plugin
list, permissions shim, UA header normalization, etc.) are injected by
its ``launch`` / ``launch_persistent_context`` entry points. Connecting
over CDP to a Chromium we launched ourselves — as the previous subprocess
design did — bypassed all of them. This driver therefore uses the
in-process persistent-context path and no longer supports cross-process
reconnection for launched browsers.

``attach(cdp_url)`` still uses ``connect_over_cdp`` for the case where
the user has launched their own warmed Chromium profile. Attach mode
DOES survive across CLI invocations — a fresh driver instance will
reconnect to the persisted CDP endpoint on first ``page(handle)`` call.
"""

from pathlib import Path
from typing import Any, ClassVar

from patchright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)

from llm_browser.drivers.base import DriverHandle
from llm_browser.drivers.playwright_base import PlaywrightDriverBase


class PatchrightDriver(PlaywrightDriverBase):
    """Default driver. Launches Chromium in-process via patchright."""

    name: ClassVar[str] = "patchright"
    # Launched mode is single-process; attach mode reconnects from the CDP
    # endpoint on demand (see page()).
    supports_reconnect: ClassVar[bool] = True

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None  # set only in attach mode
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    # --- Lifecycle ---

    def launch(
        self,
        user_data_dir: Path,
        url: str | None,
        headed: bool,
        executable_path: str | None = None,
    ) -> DriverHandle:
        user_data_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            **_build_launch_kwargs(user_data_dir, headed, executable_path)
        )
        self._page = _first_page_or_new(self._context)
        if url is not None:
            self._page.goto(url)
        return DriverHandle(driver=self.name, user_data_dir=str(user_data_dir))

    def attach(self, cdp_url: str) -> DriverHandle:
        """Attach to an already-running Chromium exposing CDP at cdp_url."""
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.connect_over_cdp(cdp_url)
        self._context = _first_context_or_new(self._browser)
        self._page = self._context.new_page()
        return DriverHandle(
            driver=self.name,
            pid=None,
            endpoint=cdp_url,
            user_data_dir="",
            extra={"attached": "1"},
        )

    def page(self, handle: DriverHandle) -> Any:
        if self._page is None:
            self._reattach_or_raise(handle)
        assert self._page is not None
        return self._page

    def latest_tab(self, handle: DriverHandle) -> Any:
        if self._context is None:
            self._reattach_or_raise(handle)
        assert self._context is not None
        if not self._context.pages:
            raise RuntimeError("No tabs open.")
        self._page = self._context.pages[-1]
        return self._page

    def close(self, handle: DriverHandle) -> None:
        if _is_attached(handle):
            self._close_attached()
        else:
            self._close_launched()
        self._page = None
        self._context = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def status(self, handle: DriverHandle) -> bool:
        if self._page is not None:
            return True
        # Attached mode is recoverable from the persisted CDP endpoint even
        # when the driver instance is fresh (e.g. a new CLI invocation).
        return _is_attached(handle) and bool(handle.endpoint)

    # --- Internals ---

    def _reattach_or_raise(self, handle: DriverHandle) -> None:
        """Rebuild live state from ``handle`` when the process is fresh.

        Only attach mode is recoverable: the CDP endpoint points at a
        Chromium we didn't launch and didn't kill. Launched mode is gone
        once Python exits — the persistent context died with it.
        """
        if not _is_attached(handle) or not handle.endpoint:
            raise RuntimeError(
                "PatchrightDriver has no live page. Call launch() or attach() "
                "first; launched mode does not survive across CLI invocations "
                "(use `llm-browser run` end-to-end, or switch to attach mode)."
            )
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.connect_over_cdp(handle.endpoint)
        self._context = _first_context_or_new(self._browser)
        self._page = _last_page_or_new(self._context)

    def _close_attached(self) -> None:
        """Release our tab + CDP connection. Never kills the remote Chromium."""
        if self._page is not None:
            try:
                self._page.close()
            except Exception:
                pass
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    def _close_launched(self) -> None:
        """Close the persistent context, which stops Chromium."""
        if self._context is not None:
            self._context.close()


# --- Module helpers ---


def _build_launch_kwargs(
    user_data_dir: Path, headed: bool, executable_path: str | None
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "user_data_dir": str(user_data_dir),
        "headless": not headed,
        "no_viewport": True,
    }
    if executable_path is not None:
        kwargs["executable_path"] = executable_path
    return kwargs


def _first_page_or_new(context: BrowserContext) -> Page:
    return context.pages[0] if context.pages else context.new_page()


def _last_page_or_new(context: BrowserContext) -> Page:
    return context.pages[-1] if context.pages else context.new_page()


def _first_context_or_new(browser: Browser) -> BrowserContext:
    return browser.contexts[0] if browser.contexts else browser.new_context()


def _is_attached(handle: DriverHandle) -> bool:
    return handle.extra.get("attached") == "1"
