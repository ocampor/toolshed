"""BrowserSession: browser lifecycle + direct interaction API."""

from __future__ import annotations

import logging
from collections.abc import Collection
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from llm_browser import session_input, waits
from llm_browser.behavior import Behavior, BehaviorRuntime, Jitter
from llm_browser.chrome import (
    is_process_alive,
    kill_detached_chromium,
    spawn_detached_chromium,
)
from llm_browser.constants import (
    DEFAULT_FIND_TIMEOUT_MS,
    DEFAULT_POLL_INTERVAL_MS,
    DEFAULT_SETTLE_MS,
    DEFAULT_STATE_DIR,
    DEFAULT_URL_SCHEMES,
    DEFAULT_WAIT_TIMEOUT_MS,
    LOGGER_NAME,
    PICK_MAX_CANDIDATES,
    PROBE_TEXT_MAX_CHARS,
)
from llm_browser.drivers import Driver, DriverHandle, resolve_driver
from llm_browser.html import SanitizeLevel, sanitize_page_html
from llm_browser.models import (
    CaptureMode,
    check_settle_budget,
    PageProbe,
    SessionInfo,
    SessionResult,
    WaitState,
)
from llm_browser.parse import ExtractField
from llm_browser.results import BytesResult
from llm_browser.state import STATE_FILENAME, SessionState
from llm_browser.scripts import page_probe_js
from llm_browser.selectors import (
    Selector,
    css_string,
    expect_single,
    resolve_selector,
)

logger = logging.getLogger(LOGGER_NAME)


def checked_url(
    url: str, allowed_schemes: Collection[str] = DEFAULT_URL_SCHEMES
) -> str:
    """A schemeless url is rejected too: a relative path is not a navigable target."""
    if urlsplit(url).scheme not in allowed_schemes:
        raise ValueError(f"url must be {' or '.join(allowed_schemes)}: {url}")
    return url


class BrowserSession:
    """Browser lifecycle management + page interaction API.

    Each instance manages a persistent browser session through a pluggable
    Driver and provides high-level methods for page interaction.
    """

    def __init__(
        self,
        session_id: str = "default",
        state_dir: Path = DEFAULT_STATE_DIR,
        behavior: Behavior | None = None,
        capture: CaptureMode = "screenshot",
        capture_level: SanitizeLevel = SanitizeLevel.HIGH,
        driver: Driver | str | None = None,
        executable_path: str | Path | None = None,
        stateless: bool = False,
    ) -> None:
        self.session_id = session_id
        self.state_dir = state_dir
        self.stateless = stateless
        self.session_dir = state_dir / "sessions" / session_id
        self.state = SessionState(self.session_dir / STATE_FILENAME, stateless)
        self._user_data_dir = self.session_dir / "user-data"
        self.driver: Driver = resolve_driver(driver)
        self._page: Any | None = None
        self.behavior: Behavior = behavior if behavior is not None else Behavior.off()
        self.behavior_runtime: BehaviorRuntime = self.behavior.runtime()
        self.capture: CaptureMode = capture
        # How hard a failure's DOM snapshot is sanitized. `high` drops every
        # src/href, which is right for reading and wrong when the link is the
        # thing you need to see.
        self.capture_level: SanitizeLevel = capture_level
        self.executable_path: str | None = (
            str(executable_path) if executable_path is not None else None
        )

    # --- Lifecycle ---

    def _ensure_dirs(self) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._user_data_dir.mkdir(parents=True, exist_ok=True)

    def _handle_from_state(self, info: SessionInfo) -> DriverHandle:
        extra: dict[str, str] = {}
        if info.mode == "attached":
            extra["attached"] = "1"
        if info.target_id:
            extra["target_id"] = info.target_id
        return DriverHandle(
            driver=info.driver,
            pid=info.pid,
            endpoint=info.cdp_url or None,
            user_data_dir=info.user_data_dir,
            extra=extra,
        )

    def _attached_info(self, handle: DriverHandle, cdp_url: str) -> SessionInfo:
        return SessionInfo(
            pid=None,
            cdp_url=handle.endpoint or cdp_url,
            user_data_dir=handle.user_data_dir,
            driver=handle.driver,
            mode="attached",
            target_id=handle.extra.get("target_id"),
        )

    def launch(self, url: str | None = None, headed: bool = True) -> SessionResult:
        """Launch the browser and connect."""
        target = checked_url(url) if url is not None else None
        self._ensure_dirs()
        logger.info("llm-browser session dir: %s", self.session_dir)
        handle = self.driver.launch(
            self._user_data_dir, target, headed, executable_path=self.executable_path
        )
        info = SessionInfo(
            pid=handle.pid,
            cdp_url=handle.endpoint or "",
            user_data_dir=handle.user_data_dir,
            driver=handle.driver,
            mode="launched",
        )
        self.state.save(info)
        self._page = self.driver.page(handle)
        return SessionResult(
            status="open",
            url=self.driver.page_url(self._page) if self._page else None,
        )

    def attach(self, cdp_url: str) -> SessionResult:
        """Attach to an already-running Chromium exposing CDP at cdp_url.

        The remote browser is NOT killed on close(); only our connection and
        the tab we opened are cleaned up. Use this against a user-launched
        Chromium with a warmed profile to pass fingerprint-grade bot
        detection (Cloudflare, PerimeterX, DataDome).
        """
        return self._open_attached(cdp_url, self.driver.attach(cdp_url))

    def attach_to_tab(self, cdp_url: str, target_id: str) -> SessionResult:
        """Attach to one existing tab of a running Chromium by its target id.

        ``(cdp_url, target_id)`` is the full address of a tab: a caller can
        hold it between invocations instead of a state file.
        """
        handle = self.driver.attach_to_tab(cdp_url, target_id)
        return self._open_attached(cdp_url, handle)

    def _open_attached(self, cdp_url: str, handle: DriverHandle) -> SessionResult:
        if not self.stateless:
            self.session_dir.mkdir(parents=True, exist_ok=True)
            logger.info("llm-browser session dir: %s (attached)", self.session_dir)
        info = self._attached_info(handle, cdp_url)
        self.state.save(info)
        self._page = self.driver.page(handle)
        return SessionResult(
            status="open",
            url=self.driver.page_url(self._page) if self._page else None,
            cdp_url=cdp_url,
            target_id=info.target_id,
        )

    def launch_detached(
        self,
        url: str | None = None,
        headed: bool = True,
        executable_path: str | Path | None = None,
        user_data_dir: str | Path | None = None,
    ) -> SessionResult:
        """Spawn Chromium as a detached process and attach to it over CDP.

        Gives you a browser that outlives this Python process, so later CLI
        calls can reconnect via the persisted CDP URL. Only ``patchright``
        supports the attach half; other drivers raise ``NotImplementedError``.

        Point ``executable_path`` at your real Chrome/Chromium and
        ``user_data_dir`` at your real profile to reuse a warmed identity
        (cookies, TLS state, stored Cloudflare tokens). Chromium refuses to
        start a second instance against an already-open profile — close any
        running Chrome first, or use a dedicated profile directory.

        Call ``stop_detached()`` to kill the browser when you're done.
        """
        # Validated before the spawn so a rejected URL leaves no orphan Chromium.
        target = checked_url(url) if url is not None else None
        self._ensure_dirs()
        resolved_profile = (
            Path(user_data_dir) if user_data_dir is not None else self._user_data_dir
        )
        resolved_exe = (
            str(executable_path)
            if executable_path is not None
            else self.executable_path
        )
        # Whatever was already recorded, so a failed attach can put it back:
        # clearing the file would strand an *earlier* detached browser with no
        # pid anywhere for `stop_detached` to kill.
        recorded = self.state.load()
        pid, cdp_url = spawn_detached_chromium(
            resolved_profile, headed=headed, executable_path=resolved_exe
        )
        logger.info(
            "llm-browser detached Chromium pid=%d cdp=%s profile=%s",
            pid,
            cdp_url,
            resolved_profile,
        )
        # Recorded before the attach: a browser nothing knows the pid of is a
        # browser nobody can stop, and `attach` is the step most likely to
        # fail (wrong driver, CDP not up yet, a profile already in use).
        self.state.save(
            SessionInfo(
                pid=pid,
                cdp_url=cdp_url,
                user_data_dir=str(resolved_profile),
                driver=self.driver.name,
                mode="attached",
            )
        )
        try:
            handle = self.driver.attach(cdp_url)
        except BaseException:
            kill_detached_chromium(pid)
            self.state.restore(recorded)
            raise
        info = SessionInfo(
            pid=pid,
            cdp_url=handle.endpoint or cdp_url,
            user_data_dir=str(resolved_profile),
            driver=handle.driver,
            mode="attached",
            target_id=handle.extra.get("target_id"),
        )
        self.state.save(info)
        self._page = self.driver.page(handle)
        if target is not None:
            self.driver.goto(self._page, target, "domcontentloaded")
        # A user-profile Chromium auto-opens its default new-tab page on
        # startup; combined with attach()'s new_page() that leaves at least
        # two tabs in the context. Trim the context down to the tab the
        # caller asked for.
        self.driver.close_other_tabs(handle, self._page)
        return SessionResult(
            status="open",
            url=self.driver.page_url(self._page) if self._page else None,
            cdp_url=cdp_url,
            target_id=info.target_id,
        )

    def stop_detached(self) -> SessionResult:
        """Release our CDP connection AND kill the detached Chromium.

        Use this to shut down a browser previously started with
        ``launch_detached()``. A plain ``close()`` only releases the
        connection and leaves the browser running.
        """
        info = self.state.load()
        if info is not None:
            self.driver.close(self._handle_from_state(info))
            if info.pid:
                kill_detached_chromium(info.pid)
        self._page = None
        self.state.clear()
        return SessionResult(status="closed")

    def connect(self) -> Any:
        """Connect to a running browser and return the active page."""
        info = self.state.load()
        if info is None:
            raise RuntimeError("No browser session. Run 'llm-browser open' first.")
        if info.pid and not is_process_alive(info.pid):
            self.state.clear()
            raise RuntimeError(
                "Browser process is no longer running. Run 'llm-browser open' again."
            )
        self._page = self.driver.page(self._handle_from_state(info))
        return self._page

    def get_page(self) -> Any:
        """Get the current page, connecting if needed.

        Calls on the raw page returned here BYPASS humanization — only the
        ``BrowserSession`` input methods honor ``Behavior.human()`` timing
        and mouse-path jitter.
        """
        if self._page is None:
            self.connect()
        assert self._page is not None
        return self._page

    def latest_tab(self) -> Any:
        """Switch to the most recently opened tab and return it."""
        info = self.state.load()
        if info is None:
            raise RuntimeError("No browser session.")
        if self._page is None:
            self._page = self.driver.page(self._handle_from_state(info))
        self._page = self.driver.latest_tab(self._handle_from_state(info))
        return self._page

    def close(self) -> SessionResult:
        """Close the browser and clean up.

        In attached mode, the remote Chromium process is NEVER killed —
        only our tab and the CDP connection are released.

        The user-data-dir is never auto-removed (profile reuse is
        intentional). Nothing else is left behind to remove: the session
        directory holds state, never captures.
        """
        info = self.state.load()
        if info is not None:
            self.driver.close(self._handle_from_state(info))
        self._page = None
        self.state.clear()
        return SessionResult(status="closed")

    def status(self) -> SessionResult:
        """Return current browser status."""
        info = self.state.load()
        if info is None:
            return SessionResult(status="closed")
        if self.driver.status(self._handle_from_state(info)):
            return SessionResult(
                status="open",
                cdp_url=info.cdp_url or None,
                target_id=info.target_id,
            )
        self.state.clear()
        return SessionResult(status="closed")

    def scroll(self, dx: int, dy: int, selector: Selector | None = None) -> None:
        """Scroll by a mouse-wheel delta, over ``selector`` when one is given.

        A wheel event goes to whatever is under the pointer, so name the
        element when the thing you mean to scroll is not the document.
        """
        locator = self.find(selector) if selector is not None else None
        self.driver.scroll(self.get_page(), dx, dy, locator)

    def screenshot_bytes(self, selector: Selector | None = None) -> bytes:
        """PNG bytes of the current page, or of ``selector`` alone when given.

        Nothing is written into the session dir either way.
        """
        if selector is None:
            return self.driver.screenshot_bytes(self.get_page())
        return self.driver.screenshot_element_bytes(self.find(selector))

    def dom_snapshot(self, level: SanitizeLevel | None = None) -> str:
        """Sanitized HTML of the whole current page, as text.

        ``level`` defaults to the session's ``capture_level``.
        """
        return sanitize_page_html(
            self.driver.content(self.get_page()),
            self.capture_level if level is None else level,
        )

    def download_file(
        self, selector: Selector, *, timeout: int = DEFAULT_FIND_TIMEOUT_MS
    ) -> BytesResult:
        """Click ``selector`` and return what the browser downloaded.

        The bytes come back in memory under the filename the server
        suggested — remote input, so a caller writing it to disk takes the
        basename first. ``timeout`` bounds both halves: finding the element
        and waiting for the download it starts.
        """
        element = self.find(selector, timeout=timeout)

        def trigger() -> None:
            session_input.click_element(self, element)

        return self.driver.download_bytes(self.get_page(), trigger, timeout)

    # --- Interaction ---

    def goto(
        self,
        url: str,
        wait_until: str = "domcontentloaded",
        *,
        allowed_schemes: Collection[str] = DEFAULT_URL_SCHEMES,
    ) -> None:
        target = checked_url(url, allowed_schemes)
        self.driver.goto(self.get_page(), target, wait_until)

    def find(
        self,
        selector: Selector,
        state: WaitState = "visible",
        timeout: int = DEFAULT_FIND_TIMEOUT_MS,
    ) -> Any:
        """Find exactly one element. Raises ValueError if multiple match.

        Ambiguity is a mistake, not something to wait out, so it is checked
        before the poll — otherwise a selector matching two elements burns the
        whole budget and reports a misleading timeout. It is checked again
        after, because the wait is what makes a match appear, and counting
        never waits.
        """
        page = self.get_page()
        expect_single(
            self.driver, resolve_selector(self.driver, page, selector), selector
        )
        self.wait_for_element(selector, state=state, timeout=timeout)
        return expect_single(
            self.driver, resolve_selector(self.driver, page, selector), selector
        )

    def find_all(
        self,
        selector: Selector,
        state: WaitState = "attached",
        timeout: int = DEFAULT_FIND_TIMEOUT_MS,
    ) -> Any:
        """Find all matching elements, waiting for at least one."""
        self.wait_for_element(selector, state=state, timeout=timeout)
        return resolve_selector(self.driver, self.get_page(), selector)

    def element_exists(
        self,
        selector: Selector,
        timeout: int = DEFAULT_WAIT_TIMEOUT_MS,
        *,
        state: WaitState = "attached",
    ) -> bool:
        """Whether ``selector`` reaches ``state`` within ``timeout``; never raises.

        The bool half of ``wait_for_element``: ``state`` is there so "is the
        error visible" and "is the input gone" are answerable without an
        exception, the way a racing poll needs them.
        """
        try:
            self.wait_for_element(selector, state=state, timeout=timeout)
        except TimeoutError:
            return False
        return True

    def wait_for_element(
        self,
        selector: Selector,
        *,
        state: WaitState = "attached",
        timeout: int = DEFAULT_WAIT_TIMEOUT_MS,
        interval: int = DEFAULT_POLL_INTERVAL_MS,
        settle: int = DEFAULT_SETTLE_MS,
    ) -> None:
        """Poll until ``selector`` reaches ``state``; raise ``TimeoutError`` if not.

        The one wait: it polls from Python on a jittered cadence instead of
        handing the wait to the driver, so no in-page script is injected and
        the timeout carries the selector and state in its message. ``settle``
        applies to ``state="stable"`` — how long the element's text has to
        hold still, and has to fit inside ``timeout``. Use ``element_exists``
        when you want a bool back.
        """
        check_settle_budget(state, settle, timeout)
        waits.poll_for_state(
            self.driver,
            self.get_page(),
            selector,
            state,
            timeout_ms=timeout,
            interval_ms=interval,
            rng=self.behavior_runtime.rng,
            settle_ms=settle,
        )

    def wait_for_load_state(
        self, state: str = "domcontentloaded", timeout: int = 10_000
    ) -> None:
        """Wait for page load state (domcontentloaded, load, networkidle)."""
        self.driver.wait_for_load(self.get_page(), state, timeout)

    # --- Input ---
    #
    # Thin delegations to ``session_input``, which owns the resolve/pace/
    # humanize decisions. Callers above the session use these, never the driver.

    def click(
        self,
        selector: Selector,
        *,
        dispatch: bool = False,
        humanize: bool | None = None,
        timeout: int = DEFAULT_FIND_TIMEOUT_MS,
    ) -> None:
        session_input.click(
            self, selector, dispatch=dispatch, humanize=humanize, timeout=timeout
        )

    def fill(
        self, selector: Selector, value: str, *, timeout: int = DEFAULT_FIND_TIMEOUT_MS
    ) -> None:
        session_input.fill(self, selector, value, timeout=timeout)

    def type(
        self,
        selector: Selector,
        value: str,
        *,
        delay_ms: int | Jitter = 0,
        humanize: bool | None = None,
        timeout: int = DEFAULT_FIND_TIMEOUT_MS,
    ) -> None:
        session_input.type(
            self,
            selector,
            value,
            delay_ms=delay_ms,
            humanize=humanize,
            timeout=timeout,
        )

    def press(
        self,
        selector: Selector | None,
        key: str,
        *,
        timeout: int = DEFAULT_FIND_TIMEOUT_MS,
    ) -> None:
        session_input.press(self, selector, key, timeout=timeout)

    def select_option(
        self, selector: Selector, value: str, *, timeout: int = DEFAULT_FIND_TIMEOUT_MS
    ) -> None:
        session_input.select_option(self, selector, value, timeout=timeout)

    def set_checked(
        self,
        selector: Selector,
        checked: bool,
        *,
        timeout: int = DEFAULT_FIND_TIMEOUT_MS,
    ) -> None:
        session_input.set_checked(self, selector, checked, timeout=timeout)

    def pick(self, selector: Selector, value: str) -> None:
        """Click the element matching text from a list of elements.

        Two round-trips per candidate, so a selector that named something
        broader than the item container is refused rather than walked.
        """
        locator = self.find_all(selector)
        count = self.driver.count(locator)
        if count > PICK_MAX_CANDIDATES:
            raise ValueError(
                f"Expected list items, scanned {count}; "
                "selector must match the item container"
            )
        if count == 1:
            session_input.click_element(self, self.driver.first(locator))
            return
        for i in range(count):
            item = self.driver.nth(locator, i)
            if self.driver.text_content(item) == value:
                session_input.click_element(self, item)
                return
        raise ValueError(f"No element with text '{value}' for selector {selector!r}")

    def frame(self, selector: Selector, timeout: int = DEFAULT_FIND_TIMEOUT_MS) -> Any:
        """Enter an iframe, returning the Frame."""
        element = self.find(selector, state="attached", timeout=timeout)
        return self.driver.enter_frame(element)

    def parse_elements(
        self,
        selector: Selector,
        extract: dict[str, ExtractField],
    ) -> list[dict[str, str | None]]:
        """Extract structured data from matching elements.

        ``extract`` maps output field names to ``ExtractField`` specs that say
        which child selector to descend into and which attribute/property to
        read. When ``child_selector`` is None the value is read off the row
        element itself.
        """
        locator = resolve_selector(self.driver, self.get_page(), selector)
        spec = {
            name: {"child_selector": f.child_selector, "attribute": f.attribute}
            for name, f in extract.items()
        }
        return self.driver.extract_rows(locator, spec)

    def dom(
        self,
        selector: Selector,
        max_depth: int = 0,
        level: SanitizeLevel = SanitizeLevel.LOW,
    ) -> str:
        """Return cleaned HTML snippet of an element."""
        from llm_browser.html import sanitize_html_fragment

        raw: str = self.driver.evaluate(self.find(selector), "el => el.outerHTML")
        return sanitize_html_fragment(raw, max_depth, level)

    def probe(
        self,
        selector: Selector | None = None,
        max_chars: int = PROBE_TEXT_MAX_CHARS,
    ) -> PageProbe:
        """Read the page's human-attention signals in a single evaluate.

        Pass ``selector`` to also capture that element's rendered text in
        ``PageProbe.selector_text``. Feed the result to
        :func:`llm_browser.probe.human_needed`.
        """
        script = page_probe_js(
            css_string(selector) if selector is not None else None, max_chars
        )
        raw = self.driver.evaluate(self.get_page(), script)
        return PageProbe.model_validate(raw or {})

    def evaluate(self, target: Any, script: str) -> Any:
        """Run JS in the context of a page or locator."""
        return self.driver.evaluate(target, script)
