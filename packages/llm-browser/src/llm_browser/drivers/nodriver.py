"""nodriver driver: CDP-based stealth browser with a native humanized click.

nodriver ships an async-only API (`Tab` / `Element` — no `Locator`). This driver
holds a persistent event loop and sync-bridges every Driver method by
calling `loop.run_until_complete(...)`. Single-process only — the browser
handle cannot be serialized or reconnected across CLI invocations.

Each public sync method forwards to a public `async def` sibling
(`click` → `do_click`, `text_content` → `read_text`, etc.), so tests can
await the coroutines directly and the sync surface is just a one-line bridge.

Stealth notes — detectable surfaces
-----------------------------------
Default write paths go through real CDP Input events (`isTrusted=true`):
mouse via `Input.dispatchMouseEvent`, keyboard via `Input.dispatchKeyEvent`,
focus via `DOM.focus`. Clears use Ctrl+A + Delete over CDP (not JS
`value=""`). That covers `do_click`, `do_type`, `do_fill`, `do_select_option`.

Residual JS touchpoints — all reads/polls, no DOM events dispatched:
    * `input_value`       — Runtime.callFunctionOn `(el) => el.value`.
                            Required: CDP has no live-property accessor
                            (`attrs["value"]` is the HTML attribute, which
                            diverges from `.value` after any typing).
    * `do_set_checked`    — Runtime.callFunctionOn `(el) => el.checked`.
                            Required for same reason; read decides whether
                            a toggle click is needed.
    * `do_wait_for_load`  — Runtime.evaluate `document.readyState` polled
                            every 250ms. nodriver 0.48 has no CDP lifecycle
                            hook (`tab.wait()` is a plain sleep).
    * `evaluate` / `dom`  — arbitrary user-supplied JS. Inherently JS.

Opt-in synthetic-event escape hatches (emit `isTrusted=false` — detectable):
    * `dispatch_event`           — fires `new Event(...)`. Use sparingly.
    * `do_click(dispatch=True)`  — JS `HTMLElement.click()` for overlay bypass.

Detectors that fingerprint Runtime-domain traffic itself (rare; high false-
positive rate for legit DevTools) could spot the reads. Detectors that watch
DOM event `isTrusted` (common) will only flag the opt-in escape hatches.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ClassVar, Coroutine, TypeVar

from llm_browser.drivers.base import Driver, DriverHandle, load_optional_module

# Virtual key codes for trusted keyboard events via Input.dispatchKeyEvent.
# Using JS element.value="" would bypass input/change events — detectable.
KEY_A_VK = 65
KEY_DELETE_VK = 46
MODIFIER_CTRL = 2

# Named keys → (DOM `key`, DOM `code`, Windows VK code) for dispatch_key_event.
# Enter is the common case (submit on chat UIs); extend as other named keys
# are needed. Single-character keys fall back to text-input semantics.
NAMED_KEYS: dict[str, tuple[str, str, int]] = {
    "Enter": ("Enter", "Enter", 13),
    "Tab": ("Tab", "Tab", 9),
    "Escape": ("Escape", "Escape", 27),
    "Backspace": ("Backspace", "Backspace", 8),
    "Delete": ("Delete", "Delete", 46),
    "ArrowUp": ("ArrowUp", "ArrowUp", 38),
    "ArrowDown": ("ArrowDown", "ArrowDown", 40),
    "ArrowLeft": ("ArrowLeft", "ArrowLeft", 37),
    "ArrowRight": ("ArrowRight", "ArrowRight", 39),
}

T = TypeVar("T")

READY_STATES: dict[str, set[str]] = {
    "load": {"complete"},
    "domcontentloaded": {"interactive", "complete"},
    "networkidle": {"complete"},
}


@dataclass
class NodriverLocator:
    """Handle for a nodriver selector resolution.

    Carries either a `selector` (resolve lazily on use) or a pre-resolved
    `element` (from nth/first). Resolution results are cached back onto this
    object so repeated count/first/all calls don't re-round-trip CDP.
    """

    tab: Any
    selector: str | None = None
    element: Any = None
    elements: list[Any] | None = None

    def __post_init__(self) -> None:
        if self.selector is None and self.element is None:
            raise ValueError("NodriverLocator needs either selector or element")


class NodriverDriver(Driver):
    """nodriver-backed driver. Native humanized click via `element.click()`."""

    name: ClassVar[str] = "nodriver"
    supports_reconnect: ClassVar[bool] = False

    def __init__(self, **start_kwargs: Any) -> None:
        self.start_kwargs = start_kwargs
        self.browser: Any = None
        self.tab: Any = None
        self.loop: asyncio.AbstractEventLoop | None = None

    # --- Sync bridge ---

    def run(self, coro: Coroutine[Any, Any, T]) -> T:
        if self.loop is None:
            raise RuntimeError("Event loop not running. Call launch() first.")
        return self.loop.run_until_complete(coro)

    # --- Lifecycle ---

    def launch(
        self,
        user_data_dir: Path,
        url: str | None,
        headed: bool,
        executable_path: str | None = None,
    ) -> DriverHandle:
        if self.loop is not None:
            raise RuntimeError(
                "NodriverDriver.launch() called twice; call close() first"
            )
        nodriver = load_optional_module("nodriver", "nodriver")
        user_data_dir.mkdir(parents=True, exist_ok=True)
        self.loop = asyncio.new_event_loop()
        start_kwargs = dict(self.start_kwargs)
        if executable_path is not None:
            start_kwargs.setdefault("browser_executable_path", executable_path)
        self.browser = self.run(
            nodriver.start(
                user_data_dir=str(user_data_dir),
                headless=not headed,
                **start_kwargs,
            )
        )
        self.tab = self.browser.main_tab
        if url is not None:
            self.run(self.tab.get(url))
        return DriverHandle(driver=self.name, user_data_dir=str(user_data_dir))

    def page(self, handle: DriverHandle) -> Any:
        if self.tab is None:
            raise RuntimeError(
                "NodriverDriver has no live tab. Call launch() first; "
                "this driver does not support cross-process reconnection."
            )
        return self.tab

    def latest_tab(self, handle: DriverHandle) -> Any:
        if self.browser is None or not self.browser.tabs:
            raise RuntimeError("No tabs open.")
        self.tab = self.browser.tabs[-1]
        return self.tab

    def close(self, handle: DriverHandle) -> None:
        if self.browser is not None and self.loop is not None:
            # Shutdown is racy — CDP websocket may already be disconnected.
            # Swallow so subsequent state reset always runs.
            try:
                self.run(self.browser.stop())
            except Exception:
                pass
        if self.loop is not None and not self.loop.is_closed():
            self.loop.close()
        self.browser = None
        self.tab = None
        self.loop = None

    def status(self, handle: DriverHandle) -> bool:
        return self.tab is not None

    # --- Element resolution ---

    def resolve(self, page: Any, selector: str) -> Any:
        return NodriverLocator(tab=page, selector=selector)

    async def resolve_element(self, loc: NodriverLocator) -> Any:
        if loc.element is not None:
            return loc.element
        assert loc.selector is not None
        loc.element = await loc.tab.select(loc.selector)
        return loc.element

    async def resolve_all(self, loc: NodriverLocator) -> list[Any]:
        if loc.elements is not None:
            return loc.elements
        if loc.selector is None:
            loc.elements = [await self.resolve_element(loc)]
            return loc.elements
        loc.elements = list(await loc.tab.select_all(loc.selector))
        return loc.elements

    async def apply_script(self, loc: NodriverLocator, script: str) -> Any:
        el = await self.resolve_element(loc)
        return await el.apply(script)

    # --- Interactions ---

    def click(self, locator: Any, *, dispatch: bool = False) -> None:
        self.run(self.do_click(locator, dispatch))

    async def do_click(self, loc: NodriverLocator, dispatch: bool) -> None:
        """Default path uses Input.dispatchMouseEvent (event.isTrusted=true).

        nodriver's own `element.click()` is a Runtime.callFunctionOn wrapper
        around the JS `HTMLElement.click()` method — the resulting DOM event
        is NOT trusted. `element.mouse_click()` is the real native path.

        `dispatch=True` opts into the JS click as an overlay-bypass escape
        hatch (detectable; use sparingly).
        """
        el = await self.resolve_element(loc)
        if dispatch:
            await el.click()
        else:
            await el.mouse_click()

    def fill(self, locator: Any, text: str) -> None:
        self.run(self.do_fill(locator, text))

    async def do_fill(self, loc: NodriverLocator, text: str) -> None:
        """Trusted clear + trusted type. Equivalent to do_type on an empty field."""
        await self.clear_trusted(loc)
        await self.do_type(loc, text, delay_ms=0)

    def type(self, locator: Any, text: str, *, delay_ms: int = 0) -> None:
        self.run(self.do_type(locator, text, delay_ms))

    async def do_type(self, loc: NodriverLocator, text: str, delay_ms: int) -> None:
        """Per-char CDP Input.dispatchKeyEvent via nodriver's send_keys.

        send_keys focuses via JS apply() then dispatches a real `char` key event
        per character — event.isTrusted=true on the resulting input/keydown.
        """
        el = await self.resolve_element(loc)
        if delay_ms <= 0:
            await el.send_keys(text)
            return
        for ch in text:
            await el.send_keys(ch)
            await asyncio.sleep(delay_ms / 1000.0)

    async def clear_trusted(self, loc: NodriverLocator) -> None:
        """CDP focus → Ctrl+A (selectAll) → Delete. All isTrusted=true.

        Replaces `element.clear_input()` which sets value="" via JS and fires
        no input/change events — a detectable value discontinuity.
        """
        el = await self.resolve_element(loc)
        nodriver = load_optional_module("nodriver", "nodriver")
        cdp = nodriver.cdp
        await loc.tab.send(cdp.dom.focus(backend_node_id=el.backend_node_id))
        for event_type, extra in (
            ("rawKeyDown", {"modifiers": MODIFIER_CTRL, "commands": ["selectAll"]}),
            ("keyUp", {"modifiers": MODIFIER_CTRL}),
        ):
            await loc.tab.send(
                cdp.input_.dispatch_key_event(
                    event_type,
                    key="a",
                    code="KeyA",
                    windows_virtual_key_code=KEY_A_VK,
                    **extra,
                )
            )
        for event_type in ("rawKeyDown", "keyUp"):
            await loc.tab.send(
                cdp.input_.dispatch_key_event(
                    event_type,
                    key="Delete",
                    code="Delete",
                    windows_virtual_key_code=KEY_DELETE_VK,
                )
            )

    def press(self, locator: Any, key: str) -> None:
        self.run(self.do_press(locator, key))

    async def do_press(self, loc: NodriverLocator, key: str) -> None:
        el = await self.resolve_element(loc)
        if key in NAMED_KEYS:
            await el.focus()
            await self._dispatch_named_key(loc.tab, key)
        else:
            # Single-character keys: let send_keys handle text-input semantics.
            await el.send_keys(key)

    def press_focused(self, page: Any, key: str) -> None:
        self.run(self._press_focused_async(page, key))

    async def _press_focused_async(self, page: Any, key: str) -> None:
        # Nodriver has no page-level keyboard API; dispatch via CDP Input on
        # whatever element currently holds focus.
        await self._dispatch_named_key(page, key)

    async def _dispatch_named_key(self, tab: Any, key: str) -> None:
        """Emit keyDown+keyUp via CDP with the correct key/code/VK triplet.

        For named keys like 'Enter', just passing ``key=code="Enter"`` leaves
        ``windowsVirtualKeyCode=0`` and many apps (ChatGPT included) treat the
        event as text input — so Enter gets typed instead of submitting. The
        Windows VK code is what makes Chromium generate a real keypress.
        """
        nodriver = load_optional_module("nodriver", "nodriver")
        cdp = nodriver.cdp
        dom_key, dom_code, vk = NAMED_KEYS.get(key, (key, key, 0))
        for event_type in ("rawKeyDown", "keyUp"):
            await tab.send(
                cdp.input_.dispatch_key_event(
                    event_type,
                    key=dom_key,
                    code=dom_code,
                    windows_virtual_key_code=vk,
                )
            )

    def select_option(self, locator: Any, value: str) -> None:
        self.run(self.do_select_option(locator, value))

    async def do_select_option(self, loc: NodriverLocator, value: str) -> None:
        """Native-click the matching <option>. Avoids synthetic change events
        that bot-detection libraries flag via event.isTrusted."""
        select_el = await self.resolve_element(loc)
        option = await select_el.query_selector(f'option[value="{value}"]')
        if option is None:
            raise RuntimeError(f"No <option value={value!r}> under select")
        await option.click()

    def set_checked(self, locator: Any, checked: bool) -> None:
        self.run(self.do_set_checked(locator, checked))

    async def do_set_checked(self, loc: NodriverLocator, checked: bool) -> None:
        """Read current state, then native-click if mismatched. The read uses
        Runtime.callFunctionOn (unavoidable to know .checked) but the write is
        a real CDP Input event, so event.isTrusted stays true."""
        el = await self.resolve_element(loc)
        current = await el.apply("(el) => el.checked")
        if bool(current) != checked:
            await el.click()

    def dispatch_event(self, locator: Any, event: str) -> None:
        """Escape hatch — dispatches a SYNTHETIC event (event.isTrusted=false).
        Most bot-detection systems flag these. Prefer click()/fill()/type()."""
        self.run(
            self.apply_script(
                locator,
                f"(el) => el.dispatchEvent(new Event({event!r}, {{bubbles: true}}))",
            )
        )

    # --- Navigation / waiting ---

    def goto(self, page: Any, url: str, wait_until: str) -> None:
        self.run(page.get(url))

    def wait_for_load(self, page: Any, state: str, timeout_ms: int) -> None:
        self.run(self.do_wait_for_load(page, state, timeout_ms))

    async def do_wait_for_load(self, page: Any, state: str, timeout_ms: int) -> None:
        """Poll `document.readyState` until it matches `state` or timeout.

        nodriver has no CDP lifecycle-event wait (tab.wait() is a plain sleep
        in 0.48, and tab.get() handles its own post-navigate wait internally).
        So this is mostly a backstop for click-triggered navigations. 250ms
        interval keeps Runtime.evaluate traffic low enough not to fingerprint.
        """
        targets = READY_STATES.get(state, {"complete"})
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_ms / 1000.0
        while loop.time() < deadline:
            if await page.evaluate("document.readyState") in targets:
                return
            await asyncio.sleep(0.25)

    def wait_for_state(self, locator: Any, state: str, timeout_ms: int) -> None:
        loc: NodriverLocator = locator
        if loc.selector is None:
            return
        self.run(loc.tab.wait_for(selector=loc.selector, timeout=timeout_ms / 1000.0))

    # --- Read / capture ---

    def text_content(self, locator: Any) -> str | None:
        return self.run(self.read_text(locator))

    async def read_text(self, loc: NodriverLocator) -> str | None:
        el = await self.resolve_element(loc)
        text: str | None = el.text
        return text

    def input_value(self, locator: Any) -> str:
        """Read-only access to the live .value property via Runtime.callFunctionOn.

        CDP has no non-JS accessor for form property state (attrs only carries
        HTML attributes, which diverge from `.value` after user input). The read
        dispatches no DOM events, so it's not a synthetic-event detection signal.
        """
        value = self.run(self.apply_script(locator, "(el) => el.value"))
        return str(value) if value is not None else ""

    def get_attribute(self, locator: Any, name: str) -> str | None:
        return self.run(self.read_attribute(locator, name))

    async def read_attribute(self, loc: NodriverLocator, name: str) -> str | None:
        el = await self.resolve_element(loc)
        value = el.attrs.get(name)
        return str(value) if value is not None else None

    def count(self, locator: Any) -> int:
        return len(self.run(self.resolve_all(locator)))

    def first(self, locator: Any) -> Any:
        elements = self.run(self.resolve_all(locator))
        if not elements:
            raise RuntimeError(f"No element matched {locator.selector!r}")
        return NodriverLocator(tab=locator.tab, element=elements[0])

    def nth(self, locator: Any, index: int) -> Any:
        elements = self.run(self.resolve_all(locator))
        return NodriverLocator(tab=locator.tab, element=elements[index])

    def all(self, locator: Any) -> list[Any]:
        elements = self.run(self.resolve_all(locator))
        return [NodriverLocator(tab=locator.tab, element=el) for el in elements]

    def child(self, locator: Any, selector: str) -> Any:
        combined = f"{locator.selector} {selector}" if locator.selector else selector
        return NodriverLocator(tab=locator.tab, selector=combined)

    def evaluate(self, target: Any, script: str) -> Any:
        if isinstance(target, NodriverLocator):
            return self.run(self.apply_script(target, f"(el) => {{ {script} }}"))
        # nodriver's tab.evaluate applies deep-serialization options that
        # override return_by_value for non-primitives, so we end up with CDP
        # RemoteObjects instead of plain data. Bypass it and call
        # Runtime.evaluate directly with plain returnByValue semantics.
        return self.run(_evaluate_by_value(target, script))

    def content(self, page: Any) -> str:
        return self.run(self.read_content(page))

    async def read_content(self, page: Any) -> str:
        html: str = await page.get_content()
        return html

    def page_url(self, page: Any) -> str:
        return str(page.url)

    def screenshot(self, page: Any, path: Path) -> None:
        self.run(page.save_screenshot(filename=str(path)))

    def expect_download(
        self, page: Any, trigger: Callable[[], None], output: Path
    ) -> Path:
        raise NotImplementedError(
            "NodriverDriver does not support expect_download in this version."
        )

    def enter_frame(self, locator: Any) -> Any:
        raise NotImplementedError(
            "NodriverDriver does not support enter_frame in this version."
        )


async def _evaluate_by_value(tab: Any, expression: str) -> Any:
    """Call CDP Runtime.evaluate with plain returnByValue (no deep serialization).

    Matches the contract every Playwright-family driver provides: a JSON-like
    value, or raise on JS error.
    """
    nodriver = load_optional_module("nodriver", "nodriver")
    cdp = nodriver.cdp

    remote_object, exception = await tab.send(
        cdp.runtime.evaluate(
            expression=expression,
            user_gesture=True,
            return_by_value=True,
            allow_unsafe_eval_blocked_by_csp=True,
        )
    )
    if exception is not None:
        raise RuntimeError(f"evaluate failed: {exception}")
    return remote_object.value if remote_object else None
