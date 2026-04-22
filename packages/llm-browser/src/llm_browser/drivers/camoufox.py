"""Camoufox driver: Firefox-based stealth browser with Playwright-compatible API.

Single-process only — Camoufox has no CDP-style reconnect. The Playwright
instance, browser, context, and page are all held in memory and torn down
by close(). Multi-CLI-call flows (open → screenshot → close across separate
processes) are not supported on this driver.
"""

import random
from pathlib import Path
from typing import Any, ClassVar

from llm_browser.behavior import Jitter, jittered_sleep
from llm_browser.drivers.base import DriverHandle, load_optional_module
from llm_browser.drivers.playwright_base import PlaywrightDriverBase

DEFAULT_CAMOUFOX_KWARGS: dict[str, Any] = {
    "humanize": True,
    "block_webrtc": True,
}

DEFAULT_TYPE_CHAR_DELAY = Jitter(min_ms=30, max_ms=90)
_RNG = random.Random()


def align_locale_with_geoip(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Inject `geoip=True` when `locale` is set without any geo override.

    Camoufox's `geoip=True` derives timezone + geolocation from the outgoing
    public IP, keeping locale/tz/IP/Accept-Language triangulation consistent.
    Callers who pin any of geoip/timezone/geolocation have signaled intent and
    are left alone.
    """
    has_locale = "locale" in kwargs
    has_geo_override = any(k in kwargs for k in ("geoip", "timezone", "geolocation"))
    if has_locale and not has_geo_override:
        return {**kwargs, "geoip": True}
    return kwargs


class CamoufoxDriver(PlaywrightDriverBase):
    """Camoufox (Firefox) driver. Inherits every interaction from the Playwright base."""

    name: ClassVar[str] = "camoufox"
    supports_reconnect: ClassVar[bool] = False

    def __init__(self, **camoufox_kwargs: Any) -> None:
        """Accept Camoufox fingerprint config (locale, os, proxy, humanize, ...).

        Passed straight to `camoufox.sync_api.Camoufox(...)` on launch, merged
        over stealth defaults (humanize, block_webrtc). Caller kwargs win on
        conflict. See `align_locale_with_geoip` for the locale→geoip rule.
        """
        merged = {**DEFAULT_CAMOUFOX_KWARGS, **camoufox_kwargs}
        self._camoufox_kwargs = align_locale_with_geoip(merged)
        self._camoufox: Any = None
        self._context: Any = None
        self._page: Any = None

    # --- Lifecycle ---

    def launch(
        self,
        user_data_dir: Path,
        url: str | None,
        headed: bool,
        executable_path: str | None = None,
    ) -> DriverHandle:
        camoufox = load_optional_module("camoufox.sync_api", "camoufox")
        user_data_dir.mkdir(parents=True, exist_ok=True)
        launch_kwargs: dict[str, Any] = {
            "headless": not headed,
            "persistent_context": True,
            "user_data_dir": str(user_data_dir),
            **self._camoufox_kwargs,
        }
        if executable_path is not None:
            launch_kwargs["executable_path"] = executable_path
        self._camoufox = camoufox.Camoufox(**launch_kwargs)
        self._context = self._camoufox.__enter__()
        self._page = (
            self._context.pages[0] if self._context.pages else self._context.new_page()
        )
        if url is not None:
            self._page.goto(url)
        return DriverHandle(driver=self.name, user_data_dir=str(user_data_dir))

    # --- Interactions (stealth overrides) ---

    def fill(self, locator: Any, text: str) -> None:
        """Clear via `.value=""` then type per-char so callers who bypass the
        action layer still emit real keyboard events (keydown/keyup/input)
        instead of a single `.value` write with no rhythm.
        """
        locator.fill("")
        if text:
            self.type(locator, text)

    def type(self, locator: Any, text: str, *, delay_ms: int = 0) -> None:
        """When delay_ms is 0 (default), type per-char with jittered 30-90ms
        pauses so direct callers get a human rhythm. Positive delay_ms is
        honored as Playwright's uniform per-char pause (explicit intent).
        """
        if delay_ms > 0:
            locator.type(text, delay=delay_ms)
            return
        for ch in text:
            locator.type(ch, delay=0)
            jittered_sleep(DEFAULT_TYPE_CHAR_DELAY, _RNG)

    def page(self, handle: DriverHandle) -> Any:
        if self._page is None:
            raise RuntimeError(
                "CamoufoxDriver has no live page. Call launch() first; "
                "this driver does not support cross-process reconnection."
            )
        return self._page

    def latest_tab(self, handle: DriverHandle) -> Any:
        if self._context is None or not self._context.pages:
            raise RuntimeError("No tabs open.")
        self._page = self._context.pages[-1]
        return self._page

    def close(self, handle: DriverHandle) -> None:
        if self._camoufox is not None:
            self._camoufox.__exit__(None, None, None)
        self._camoufox = None
        self._context = None
        self._page = None

    def status(self, handle: DriverHandle) -> bool:
        return self._page is not None
