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
`value=""`). That covers `do_click`, `do_type` and `do_fill`.

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
    * `is_visible`        — Runtime.callFunctionOn `checkVisibility`, or a
                            box read where that is missing. Required: nodriver
                            exposes no visibility API, and CDP has no
                            visibility predicate either. It is the read the
                            Python-side explicit wait polls for `visible` /
                            `hidden`; `attached` / `detached` go through
                            `count`, a plain DOM query with no Runtime
                            traffic.
    * `do_select_option`  — Runtime.callFunctionOn `js/select_option.js`,
                            which writes `selectedIndex` and fires
                            input/change. Unavoidable: a closed native select
                            has no option to click and CDP has no command for
                            choosing one. The focus ahead of it is a real
                            `DOM.focus`; the two events are the only synthetic
                            ones on a default write path, and Playwright
                            resolves the same problem the same way.
    * `evaluate` / `dom`  — arbitrary user-supplied JS. Inherently JS.

Opt-in synthetic-event escape hatches (emit `isTrusted=false` — detectable):
    * `dispatch_event`           — fires `new Event(...)`. Use sparingly.
    * `do_click(dispatch=True)`  — JS `HTMLElement.click()` for overlay bypass.

Detectors that fingerprint Runtime-domain traffic itself (rare; high false-
positive rate for legit DevTools) could spot the reads. Detectors that watch
DOM event `isTrusted` (common) will only flag the opt-in escape hatches.
"""

import asyncio
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ClassVar, Coroutine, TypeVar

from llm_browser.drivers.base import Driver
from llm_browser.drivers.handle import DriverHandle, load_optional_module
from llm_browser.results import BytesResult
from llm_browser.scripts import select_option_js

# Named keys → (DOM `key`, DOM `code`, Windows VK code) for dispatch_key_event.
# Enter is the common case (submit on chat UIs); extend as other named keys
# are needed. A single character derives its own triplet.
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

# Chord modifier → (CDP modifier bit, the modifier key's own triplet).
MODIFIERS: dict[str, tuple[int, tuple[str, str, int]]] = {
    "Alt": (1, ("Alt", "AltLeft", 18)),
    "Control": (2, ("Control", "ControlLeft", 17)),
    "Ctrl": (2, ("Control", "ControlLeft", 17)),
    "Meta": (4, ("Meta", "MetaLeft", 91)),
    "Command": (4, ("Meta", "MetaLeft", 91)),
    "Shift": (8, ("Shift", "ShiftLeft", 16)),
}

T = TypeVar("T")

SELECT_FAILURES = {
    "not-a-select": "select_option needs a <select>, got another element",
    "select-disabled": "the <select> is disabled, so {value!r} cannot be chosen",
    "missing": "no <option> matching {value!r} by value or label in the select",
    "option-disabled": "the <option> matching {value!r} is disabled",
    "group-disabled": "the <optgroup> holding {value!r} is disabled",
}
UNKNOWN_SELECT_FAILURE = "could not select the <option> matching {value!r}"

READY_STATES: dict[str, set[str]] = {
    "load": {"complete"},
    "domcontentloaded": {"interactive", "complete"},
    "networkidle": {"complete"},
}

# `checkVisibility` is the platform's own answer, and the only one that
# notices `visibility: hidden` -- a box read cannot, because a hidden element
# still has one. `checkVisibilityCSS` alone, so `opacity: 0` stays visible,
# which is what the Playwright family answers too. The fallback is the old
# box read, for an engine that has not shipped the method.
VISIBILITY_SCRIPT = (
    "(el) => el.checkVisibility"
    " ? el.checkVisibility({checkVisibilityCSS: true})"
    " : (el.offsetParent !== null || el.getClientRects().length > 0)"
)

# A script that *is* a function has to be invoked, not evaluated. The library
# writes its page scripts the way Playwright takes them — `el => el.outerHTML`,
# `page_probe.js`'s `() => {...}` — and CDP does neither by itself:
# `Runtime.evaluate` hands back the function object, and `callFunctionOn` runs
# the text as a function *body*. Both come back as `None`, silently.
FUNCTION_LITERAL = re.compile(
    r"^\s*(?:async\s+)?(?:function\b|(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>)"
)

# `// what this reads\nel => el.value` is a function too, and the cost of not
# knowing it is a silent `undefined` rather than an error. Block comments are
# not handled: the same caveat applies to `/* ... */ el => ...`.
LEADING_LINE_COMMENTS = re.compile(r"^(?:\s*//[^\n]*\n)+")


def is_function_literal(script: str) -> bool:
    """Whether ``script`` reads as a function rather than an expression.

    Anchored on the arrow or the ``function`` keyword, so a parenthesised
    expression like ``(document.title)`` is still an expression.
    """
    return FUNCTION_LITERAL.match(LEADING_LINE_COMMENTS.sub("", script)) is not None


def key_triplet(key: str) -> tuple[str, str, int]:
    """DOM `key`, DOM `code` and the Windows virtual-key code CDP needs.

    Without the VK code Chromium leaves `windowsVirtualKeyCode` at 0 and many
    apps read the event as text input — Enter gets typed instead of submitting.
    """
    if key in NAMED_KEYS:
        return NAMED_KEYS[key]
    if len(key) != 1:
        return key, key, 0
    upper = key.upper()
    if upper.isascii() and upper.isalpha():
        return key, f"Key{upper}", ord(upper)
    if key.isascii() and key.isdigit():
        return key, f"Digit{key}", ord(key)
    return key, "", 0


def split_chord(chord: str) -> tuple[list[str], str]:
    """`"Control+a"` → `(["Control"], "a")`. A bare `"+"` is the key itself."""
    parts = chord.split("+")
    key = parts[-1] or "+"
    names = [part for part in parts[:-1] if part]
    unknown = next((name for name in names if name not in MODIFIERS), None)
    if unknown is not None:
        raise ValueError(f"unknown key modifier {unknown!r} in {chord!r}")
    return names, key


async def dispatch_key_event(
    tab: Any,
    event_type: str,
    triplet: tuple[str, str, int],
    modifiers: int,
    **extra: Any,
) -> None:
    nodriver = load_optional_module("nodriver", "nodriver")
    dom_key, dom_code, vk = triplet
    await tab.send(
        nodriver.cdp.input_.dispatch_key_event(
            event_type,
            key=dom_key,
            code=dom_code,
            windows_virtual_key_code=vk,
            modifiers=modifiers,
            **extra,
        )
    )


async def press_key(
    tab: Any, key: str, modifiers: int = 0, commands: list[str] | None = None
) -> None:
    """One key, down and up, over CDP Input.

    `keyDown` carries `text` for a plain character, which is what makes
    Chromium emit the keypress and input a page is watching for; a `char`
    event alone — what nodriver's own `send_keys` sends — emits no keydown at
    all. A chord must not carry text, or `Control+a` would type an "a".
    """
    triplet = key_triplet(key)
    types_text = len(triplet[0]) == 1 and not modifiers
    extra: dict[str, Any] = {}
    if types_text:
        extra["text"] = triplet[0]
    if commands:
        extra["commands"] = commands
    await dispatch_key_event(
        tab,
        "keyDown" if types_text else "rawKeyDown",
        triplet,
        modifiers,
        **extra,
    )
    await dispatch_key_event(tab, "keyUp", triplet, modifiers)


async def press_chord(tab: Any, chord: str, commands: list[str] | None = None) -> None:
    """`"Control+a"`, with the modifiers held down around the key.

    The modifiers get their own events because a real keyboard sends them: a
    page watching for the Control keydown sees one.
    """
    names, key = split_chord(chord)
    modifiers = 0
    for name in names:
        bit, triplet = MODIFIERS[name]
        modifiers |= bit
        await dispatch_key_event(tab, "rawKeyDown", triplet, modifiers)
    await press_key(tab, key, modifiers, commands)
    for name in reversed(names):
        bit, triplet = MODIFIERS[name]
        modifiers &= ~bit
        await dispatch_key_event(tab, "keyUp", triplet, modifiers)


@dataclass
class NodriverLocator:
    """Handle for a nodriver selector resolution.

    Carries a `selector` and/or a pre-resolved `element` (from nth/all);
    `index` picks the match a re-query refers to. `query` re-reads the DOM
    every time and caches nothing, so waits and counts see a removed or
    replaced node; `resolve_element` caches its lookup in `element`, so the
    input paths keep driving the handle they first resolved.

    `parent` scopes `selector` to one element's subtree. Without it a field
    read off the third row would run the selector against the whole document
    and answer with the first row's value.
    """

    tab: Any
    selector: str | None = None
    element: Any = None
    index: int = 0
    parent: Any = None

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
            # Browser.stop() is synchronous — it calls Process.terminate()
            # directly, no event loop needed. Wrapping it in self.run() made
            # the terminate happen as a side effect of evaluating the
            # argument, then raised TypeError on the non-coroutine result,
            # which the broad except below silently ate. Shutdown is still
            # racy — the CDP websocket may already be disconnected — so the
            # except stays, but it now only catches Browser.stop()'s own
            # failures.
            try:
                self.browser.stop()
            except Exception:
                pass
            # Browser.stop() schedules its own disconnect task on this loop
            # (see the `create_task` in its first try block) but never runs
            # it — closing the loop right under a still-pending task prints
            # "Task was destroyed but it is pending!". Cancel whatever is
            # left and give the loop one more turn to unwind it quietly.
            self.drain_pending_tasks()
        if self.loop is not None and not self.loop.is_closed():
            self.loop.close()
        self.browser = None
        self.tab = None
        self.loop = None

    def drain_pending_tasks(self) -> None:
        """Cancel and await whatever is still pending on ``self.loop``.

        Best-effort: a task's own cancellation can itself raise or the loop
        can already be unusable, and none of that should stop ``close()``
        from resetting state.
        """
        if self.loop is None or self.loop.is_closed():
            return
        pending = [task for task in asyncio.all_tasks(self.loop) if not task.done()]
        if not pending:
            return
        for task in pending:
            task.cancel()
        try:
            self.loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True)
            )
        except Exception:
            pass

    def status(self, handle: DriverHandle) -> bool:
        return self.tab is not None

    # --- Element resolution ---

    def resolve(self, page: Any, selector: str) -> Any:
        return NodriverLocator(tab=page, selector=selector)

    async def require_element(self, loc: NodriverLocator) -> Any:
        """The handle a write path is about to drive — never `None`.

        The read paths are allowed a miss (rule 1); a write to an element that
        is not there is the step failing, and a `ValueError` is what
        `execute_action` turns into an `ErrorResult`. Without this the write
        paths raise `AttributeError` on `None`, which escapes `run_flow` as a
        raw traceback.
        """
        el = await self.resolve_element(loc)
        if el is None:
            raise ValueError(f"no element matched {loc.selector!r}")
        return el

    async def resolve_element(self, loc: NodriverLocator) -> Any:
        """The handle `loc` drives, or `None` when nothing matches.

        A scoped lookup goes through `query`: `tab.select` searches the whole
        document and would walk straight out of the subtree `parent` names.
        """
        if loc.element is not None:
            return loc.element
        assert loc.selector is not None
        if loc.parent is not None:
            matches = await self.query(loc)
            loc.element = matches[loc.index] if loc.index < len(matches) else None
        else:
            loc.element = await loc.tab.select(loc.selector)
        return loc.element

    async def query(self, loc: NodriverLocator) -> list[Any]:
        """Everything `loc` matches right now — the one DOM query.

        `tab.select_all` retries internally, and each retry costs a 500ms
        sleep plus a `Target.getTargets` refresh — even `timeout=0` pays one
        cycle, because the timeout is checked after it. `query_selector_all`
        is the bare `DOM.querySelectorAll` underneath it. Nothing is cached:
        a caller that needs the element to be there waits for it first
        (`BrowserSession.wait_for_element`), and a wait that re-read a cache
        would never see the page change.
        """
        if loc.selector is None:
            return [loc.element] if loc.element is not None else []
        scope = loc.parent if loc.parent is not None else loc.tab
        # nodriver answers a scope whose node has gone with `None`, not `[]`.
        return list(await scope.query_selector_all(loc.selector) or [])

    async def apply_script(self, loc: NodriverLocator, script: str) -> Any:
        el = await self.resolve_element(loc)
        if el is None:
            return None
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
        el = await self.require_element(loc)
        if dispatch:
            await el.click()
            return
        # The mouse event is dispatched at viewport coordinates, so a target
        # below the fold is clicked where it is not. `DOM.scrollIntoViewIfNeeded`
        # is the browser's own minimal scroll, which leaves a target under a
        # fixed header alone rather than parking it beneath one.
        await el.scroll_into_view()
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
        """CDP focus, then one real key per character.

        nodriver's own `send_keys` dispatches `char` events, which fire
        keypress and input but no keydown at all — so a page that watches
        keystrokes (a mask, an autocomplete, a hotkey) never reacts.
        """
        await self.focus_trusted(loc)
        for ch in text:
            await press_key(loc.tab, ch)
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)

    async def focus_trusted(self, loc: NodriverLocator) -> Any:
        """CDP `DOM.focus`, not the JS `el.focus()` nodriver reaches for."""
        el = await self.require_element(loc)
        nodriver = load_optional_module("nodriver", "nodriver")
        await loc.tab.send(nodriver.cdp.dom.focus(backend_node_id=el.backend_node_id))
        return el

    async def clear_trusted(self, loc: NodriverLocator) -> None:
        """CDP focus → Ctrl+A (selectAll) → Delete. All isTrusted=true.

        Replaces `element.clear_input()` which sets value="" via JS and fires
        no input/change events — a detectable value discontinuity. `selectAll`
        is spelled out because the chord alone tells the page what happened
        without asking Chromium to perform the edit.
        """
        await self.focus_trusted(loc)
        await press_chord(loc.tab, "Control+a", commands=["selectAll"])
        await press_key(loc.tab, "Delete")

    def press(self, locator: Any, key: str) -> None:
        self.run(self.do_press(locator, key))

    async def do_press(self, loc: NodriverLocator, key: str) -> None:
        """`key` may be a chord: `"Control+a"`, `"Shift+Tab"`."""
        await self.focus_trusted(loc)
        await press_chord(loc.tab, key)

    def press_focused(self, page: Any, key: str) -> None:
        self.run(self._press_focused_async(page, key))

    async def _press_focused_async(self, page: Any, key: str) -> None:
        # Nodriver has no page-level keyboard API; dispatch via CDP Input on
        # whatever element currently holds focus.
        await press_chord(page, key)

    def select_option(self, locator: Any, value: str) -> None:
        self.run(self.do_select_option(locator, value))

    async def do_select_option(self, loc: NodriverLocator, value: str) -> None:
        """Set the value through the select, after a real CDP focus.

        Clicking the `<option>` -- what this used to do -- is a no-op on a
        closed native select: the value never changed, and a *disabled*
        option reported success. See the module docstring for why the two
        events this fires are synthetic.
        """
        el = await self.focus_trusted(loc)
        outcome = await el.apply(select_option_js(value))
        if outcome != "ok":
            reason = SELECT_FAILURES.get(str(outcome), UNKNOWN_SELECT_FAILURE)
            raise ValueError(reason.format(value=value))

    def set_checked(self, locator: Any, checked: bool) -> None:
        self.run(self.do_set_checked(locator, checked))

    async def do_set_checked(self, loc: NodriverLocator, checked: bool) -> None:
        """Read current state, then native-click if mismatched. The read uses
        Runtime.callFunctionOn (unavoidable to know .checked) but the write is
        a real CDP Input event, so event.isTrusted stays true."""
        el = await self.require_element(loc)
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
        self.run(self.do_goto(page, url))

    async def do_goto(self, page: Any, url: str) -> None:
        """Activate first: the tab a caller navigates is the tab it drives.

        A background tab is not just invisible — Chromium throttles its timers
        and stalls `Page.captureScreenshot` on it waiting for a frame that
        never comes. One `window.open` earlier in a session is enough to leave
        the opener there for good.
        """
        await page.activate()
        await page.get(url)

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

    def is_visible(self, locator: Any) -> bool:
        return self.run(self.element_visible(locator))

    async def element_visible(self, loc: NodriverLocator) -> bool:
        """Re-queries: a handle caches the node it matched, so a node the page
        swapped out would otherwise never be seen to change state."""
        matches = await self.query(loc)
        if loc.index >= len(matches):
            return False
        try:
            return bool(await matches[loc.index].apply(VISIBILITY_SCRIPT))
        except Exception:
            # Reading a handle the page already detached fails over CDP; a node
            # that is gone is not visible, which is what `hidden` waits for.
            return False

    # --- Read / capture ---

    def text_content(self, locator: Any) -> str | None:
        return self.run(self.read_text(locator))

    async def read_text(self, loc: NodriverLocator) -> str | None:
        """A now-read (rule 1): the bare query, never `tab.select`'s retry."""
        matches = await self.query(loc)
        if loc.index >= len(matches):
            return None
        text: str | None = matches[loc.index].text
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
        if el is None:
            return None
        value = el.attrs.get(name)
        return str(value) if value is not None else None

    def count(self, locator: Any) -> int:
        return len(self.run(self.query(locator)))

    def first(self, locator: Any) -> Any:
        """Lazy while a selector is available, like Playwright's `.first`: the
        wait paths re-query it, and "nothing matched yet" is a state to wait
        for rather than an error (`element_exists` never raises)."""
        if locator.selector is None:
            return NodriverLocator(tab=locator.tab, element=locator.element)
        return NodriverLocator(
            tab=locator.tab, selector=locator.selector, parent=locator.parent
        )

    def nth(self, locator: Any, index: int) -> Any:
        """Resolved eagerly — callers iterate indices over one query — but it
        keeps the selector so the wait paths can re-query this same match."""
        elements = self.run(self.query(locator))
        return NodriverLocator(
            tab=locator.tab,
            selector=locator.selector,
            element=elements[index],
            index=index,
            parent=locator.parent,
        )

    def all(self, locator: Any) -> list[Any]:
        """Each match keeps the selector and its own index, so the handle is
        re-resolvable (rule 4) and a child read off it knows which row it is."""
        elements = self.run(self.query(locator))
        return [
            NodriverLocator(
                tab=locator.tab,
                selector=locator.selector,
                element=element,
                index=index,
                parent=locator.parent,
            )
            for index, element in enumerate(elements)
        ]

    def child(self, locator: Any, selector: str) -> Any:
        """Scoped to the element once one is resolved. A combined
        document-wide selector would answer every row with the first row's
        match, which is what `extract_rows` reads off each row."""
        if locator.element is not None:
            return NodriverLocator(
                tab=locator.tab, selector=selector, parent=locator.element
            )
        combined = f"{locator.selector} {selector}" if locator.selector else selector
        return NodriverLocator(
            tab=locator.tab, selector=combined, parent=locator.parent
        )

    def evaluate(self, target: Any, script: str) -> Any:
        """A function literal is invoked; anything else is a body or an
        expression, the way the Playwright family reads the same string."""
        if isinstance(target, NodriverLocator):
            declaration = (
                script if is_function_literal(script) else f"(el) => {{ {script} }}"
            )
            return self.run(self.apply_script(target, declaration))
        expression = f"({script})()" if is_function_literal(script) else script
        # nodriver's tab.evaluate applies deep-serialization options that
        # override return_by_value for non-primitives, so we end up with CDP
        # RemoteObjects instead of plain data. Bypass it and call
        # Runtime.evaluate directly with plain returnByValue semantics.
        return self.run(_evaluate_by_value(target, expression))

    def content(self, page: Any) -> str:
        return self.run(self.read_content(page))

    async def read_content(self, page: Any) -> str:
        html: str = await page.get_content()
        return html

    def page_url(self, page: Any) -> str:
        return str(page.url)

    def screenshot_bytes(self, page: Any) -> bytes:
        """nodriver can only capture to a file, so the capture is spooled to a
        temporary directory and read back; the directory goes with it.

        `format` is explicit: nodriver defaults to jpeg and would write JPEG
        bytes into the `.png` file every caller here asks for. The activate is
        what keeps the capture from stalling on a background tab.
        """
        with tempfile.TemporaryDirectory() as spool:
            path = Path(spool) / "screenshot.png"
            self.run(self.do_screenshot(page, path))
            return path.read_bytes()

    async def do_screenshot(self, page: Any, path: Path) -> None:
        await page.activate()
        await page.save_screenshot(filename=str(path), format="png")

    def download_bytes(
        self, page: Any, trigger: Callable[[], None], timeout_ms: int
    ) -> BytesResult:
        raise NotImplementedError(
            "NodriverDriver does not support download_bytes in this version."
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
