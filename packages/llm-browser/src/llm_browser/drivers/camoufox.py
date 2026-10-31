"""Camoufox driver: Firefox-based stealth browser with Playwright-compatible API.

Single-process only — Camoufox has no CDP-style reconnect. The Playwright
instance, browser, context, and page are all held in memory and torn down
by close(). Multi-CLI-call flows (open → screenshot → close across separate
processes) are not supported on this driver.
"""

from pathlib import Path
from typing import Any, ClassVar

from llm_browser.behavior import Jitter, jittered_sleep
from llm_browser.drivers.handle import DriverHandle, load_optional_module
from llm_browser.drivers.playwright_base import PlaywrightDriverBase

DEFAULT_CAMOUFOX_KWARGS: dict[str, Any] = {
    "humanize": True,
    "block_webrtc": True,
}

DEFAULT_TYPE_CHAR_DELAY = Jitter(min_ms=30, max_ms=90)


def align_locale_with_geoip(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Camoufox's ``geoip=True`` keeps locale, timezone and IP consistent; any explicit geo setting wins."""
    has_locale = "locale" in kwargs
    has_geo_override = any(k in kwargs for k in ("geoip", "timezone", "geolocation"))
    if has_locale and not has_geo_override:
        return {**kwargs, "geoip": True}
    return kwargs


class CamoufoxDriver(PlaywrightDriverBase):
    name: ClassVar[str] = "camoufox"
    supports_reconnect: ClassVar[bool] = False

    def __init__(self, **camoufox_kwargs: Any) -> None:
        """Passed to `Camoufox(...)` over stealth defaults (humanize, block_webrtc); caller kwargs win."""
        merged = {**DEFAULT_CAMOUFOX_KWARGS, **camoufox_kwargs}
        self._camoufox_kwargs = align_locale_with_geoip(merged)
        self._camoufox: Any = None
        self._context: Any = None
        self._page: Any = None

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

    def fill(self, locator: Any, text: str) -> None:
        """Types per char so callers bypassing the action layer still emit real key events."""
        locator.fill("")
        if text:
            self.type(locator, text)

    def type(self, locator: Any, text: str, *, delay_ms: int = 0) -> None:
        """``delay_ms=0`` types with jittered 30-90ms pauses; a positive value is Playwright's uniform pause."""
        if delay_ms > 0:
            locator.type(text, delay=delay_ms)
            return
        for ch in text:
            locator.type(ch, delay=0)
            jittered_sleep(DEFAULT_TYPE_CHAR_DELAY)

    def scroll(self, page: Any, dx: int, dy: int, locator: Any | None = None) -> None:
        """Gecko sends the wheel to whatever is under the pointer, which starts off the page.
        The pointer stays put afterwards, so hover UI can open as a side effect.
        """
        page.mouse.move(*self.wheel_target(page, locator))
        page.mouse.wheel(dx, dy)

    def wheel_target(self, page: Any, locator: Any | None) -> tuple[float, float]:
        box = locator.bounding_box() if locator is not None else None
        if box is not None:
            return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        width, height = page.evaluate("() => [window.innerWidth, window.innerHeight]")
        return width / 2, height / 2

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
