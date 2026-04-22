"""Shared Driver implementation for Playwright-compatible backends.

Used by PatchrightDriver (Chromium) and — in Phase 1 — CamoufoxDriver (Firefox).
Only lifecycle methods are left abstract; subclasses plug in their launcher.

The narrow `PwPage` / `PwLocator` / `PwFrame` Protocols below describe the
Playwright-family shape this base class actually uses. Real Patchright /
Camoufox / Playwright objects structurally satisfy them. Non-Playwright
drivers (e.g. nodriver) don't need to — they implement `Driver` directly
and never touch these Protocols.
"""

from pathlib import Path
from typing import Any, Callable, Protocol, cast

from llm_browser.behavior import (
    Behavior,
    BehaviorRuntime,
    humanized_click,
    humanized_type,
)
from llm_browser.drivers.base import Driver


# --- Narrow Playwright-family protocols ---


class PwLocator(Protocol):
    first: "PwLocator"

    def click(self) -> None: ...
    def fill(self, text: str) -> None: ...
    def type(self, text: str, delay: int = ...) -> None: ...
    def select_option(self, value: str) -> None: ...
    def check(self) -> None: ...
    def uncheck(self) -> None: ...
    def dispatch_event(self, event: str) -> None: ...
    def press(self, key: str) -> None: ...
    def wait_for(self, state: str = ..., timeout: int = ...) -> None: ...
    def text_content(self) -> str | None: ...
    def input_value(self) -> str: ...
    def get_attribute(self, name: str) -> str | None: ...
    def count(self) -> int: ...
    def nth(self, index: int) -> "PwLocator": ...
    def all(self) -> list["PwLocator"]: ...
    def locator(self, selector: str) -> "PwLocator": ...
    def evaluate(self, script: str) -> Any: ...
    def element_handle(self) -> "PwElementHandle | None": ...


class PwElementHandle(Protocol):
    def content_frame(self) -> "PwPage | None": ...


class PwDownloadInfo(Protocol):
    @property
    def value(self) -> "PwDownload": ...


class PwDownload(Protocol):
    def save_as(self, path: str) -> None: ...


class PwDownloadContext(Protocol):
    def __enter__(self) -> PwDownloadInfo: ...
    def __exit__(self, *args: Any) -> None: ...


class PwKeyboard(Protocol):
    def press(self, key: str) -> None: ...


class PwPage(Protocol):
    url: str
    keyboard: PwKeyboard

    def locator(self, selector: str) -> PwLocator: ...
    def goto(self, url: str, wait_until: str = ...) -> None: ...
    def wait_for_load_state(self, state: str = ..., timeout: int = ...) -> None: ...
    def content(self) -> str: ...
    def screenshot(self, path: str = ..., full_page: bool = ...) -> None: ...
    def evaluate(self, script: str) -> Any: ...
    def expect_download(self) -> PwDownloadContext: ...


def _pw_page(page: Any) -> PwPage:
    return cast(PwPage, page)


def _pw_loc(locator: Any) -> PwLocator:
    return cast(PwLocator, locator)


class PlaywrightDriverBase(Driver):
    """Interaction methods shared by every Playwright-compatible driver."""

    # --- Selector resolution ---

    def resolve(self, page: Any, selector: str) -> Any:
        return _pw_page(page).locator(selector)

    # --- Interactions ---

    def click(self, locator: Any, *, dispatch: bool = False) -> None:
        pw = _pw_loc(locator)
        if dispatch:
            pw.dispatch_event("click")
        else:
            pw.click()

    def fill(self, locator: Any, text: str) -> None:
        _pw_loc(locator).fill(text)

    def type(self, locator: Any, text: str, *, delay_ms: int = 0) -> None:
        _pw_loc(locator).type(text, delay=delay_ms)

    def humanized_click(
        self,
        page: Any,
        locator: Any,
        behavior: Behavior,
        runtime: BehaviorRuntime,
    ) -> None:
        humanized_click(page, locator, behavior, runtime)

    def humanized_type(
        self,
        page: Any,
        locator: Any,
        text: str,
        behavior: Behavior,
        runtime: BehaviorRuntime,
    ) -> None:
        humanized_type(page, locator, text, behavior, runtime)

    def press(self, locator: Any, key: str) -> None:
        _pw_loc(locator).press(key)

    def press_focused(self, page: Any, key: str) -> None:
        _pw_page(page).keyboard.press(key)

    def select_option(self, locator: Any, value: str) -> None:
        _pw_loc(locator).select_option(value)

    def set_checked(self, locator: Any, checked: bool) -> None:
        pw = _pw_loc(locator)
        if checked:
            pw.check()
        else:
            pw.uncheck()

    def dispatch_event(self, locator: Any, event: str) -> None:
        _pw_loc(locator).dispatch_event(event)

    # --- Navigation / waiting ---

    def goto(self, page: Any, url: str, wait_until: str) -> None:
        _pw_page(page).goto(url, wait_until=wait_until)

    def wait_for_load(self, page: Any, state: str, timeout_ms: int) -> None:
        _pw_page(page).wait_for_load_state(state, timeout=timeout_ms)

    def wait_for_state(self, locator: Any, state: str, timeout_ms: int) -> None:
        _pw_loc(locator).wait_for(state=state, timeout=timeout_ms)

    # --- Read / capture ---

    def text_content(self, locator: Any) -> str | None:
        return _pw_loc(locator).text_content()

    def input_value(self, locator: Any) -> str:
        return _pw_loc(locator).input_value()

    def get_attribute(self, locator: Any, name: str) -> str | None:
        return _pw_loc(locator).get_attribute(name)

    def count(self, locator: Any) -> int:
        return _pw_loc(locator).count()

    def first(self, locator: Any) -> Any:
        return _pw_loc(locator).first

    def nth(self, locator: Any, index: int) -> Any:
        return _pw_loc(locator).nth(index)

    def all(self, locator: Any) -> list[Any]:
        return list(_pw_loc(locator).all())

    def child(self, locator: Any, selector: str) -> Any:
        return _pw_loc(locator).locator(selector)

    def evaluate(self, target: Any, script: str) -> Any:
        return cast(PwPage | PwLocator, target).evaluate(script)

    def content(self, page: Any) -> str:
        return _pw_page(page).content()

    def page_url(self, page: Any) -> str:
        return _pw_page(page).url

    def screenshot(self, page: Any, path: Path) -> None:
        _pw_page(page).screenshot(path=str(path), full_page=False)

    def expect_download(
        self, page: Any, trigger: Callable[[], None], output: Path
    ) -> Path:
        with _pw_page(page).expect_download() as info:
            trigger()
        info.value.save_as(str(output))
        return output

    def enter_frame(self, locator: Any) -> Any:
        handle = _pw_loc(locator).element_handle()
        if handle is None:
            raise RuntimeError("Could not get handle for element")
        frame = handle.content_frame()
        if frame is None:
            raise RuntimeError("Could not find frame")
        return frame

    # --- Composite waits ---

    def wait_for_stable_text(
        self, locator: Any, quiet_ms: int, timeout_ms: int
    ) -> str | None:
        """In-page stability detection via requestAnimationFrame.

        A single Runtime.callFunctionOn starts the loop; it resolves only
        when textContent has been unchanged for ``quiet_ms`` or when
        ``timeout_ms`` has elapsed. No repeated CDP evaluate traffic.
        """
        script = _STABLE_TEXT_SCRIPT.format(
            quiet_ms=int(quiet_ms), timeout_ms=int(timeout_ms)
        )
        result = _pw_loc(locator).evaluate(script)
        return None if result is None else str(result)


_STABLE_TEXT_SCRIPT = """
(element) => new Promise((resolve) => {{
    const QUIET_MS = {quiet_ms};
    const TIMEOUT_MS = {timeout_ms};
    const deadline = performance.now() + TIMEOUT_MS;
    let lastText = element.textContent ?? '';
    let lastChange = performance.now();
    const step = () => {{
        const now = performance.now();
        const text = element.textContent ?? '';
        if (text !== lastText) {{
            lastText = text;
            lastChange = now;
        }} else if (now - lastChange >= QUIET_MS) {{
            return resolve(text);
        }}
        if (now >= deadline) return resolve(null);
        requestAnimationFrame(step);
    }};
    requestAnimationFrame(step);
}})
"""


__all__ = ["PlaywrightDriverBase"]
