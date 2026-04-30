"""BrowserSession: browser lifecycle + direct interaction API."""

import logging
from pathlib import Path
from typing import Any

from llm_browser.behavior import Behavior, BehaviorRuntime
from llm_browser.chrome import (
    is_process_alive,
    kill_detached_chromium,
    spawn_detached_chromium,
)
from llm_browser.constants import DEFAULT_STATE_DIR
from llm_browser.drivers import Driver, DriverHandle, resolve_driver
from llm_browser.html import sanitize_page_html
from llm_browser.models import (
    CaptureMode,
    SessionInfo,
    SessionResult,
)
from llm_browser.parse import ExtractField
from llm_browser.paths import prepare_output_path
from llm_browser.selectors import Selector, expect_single, resolve_selector

logger = logging.getLogger("llm_browser")


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
        driver: Driver | str | None = None,
        executable_path: str | Path | None = None,
    ) -> None:
        self.session_dir = state_dir / "sessions" / session_id
        self._state_file = self.session_dir / "state.json"
        self._user_data_dir = self.session_dir / "user-data"
        self._screenshot_path = self.session_dir / "screenshot.png"
        self._dom_path = self.session_dir / "dom.html"
        self.driver: Driver = resolve_driver(driver)
        self._page: Any | None = None
        self.behavior: Behavior = behavior if behavior is not None else Behavior.off()
        self._behavior_runtime: BehaviorRuntime = self.behavior.runtime()
        self.capture: CaptureMode = capture
        self.executable_path: str | None = (
            str(executable_path) if executable_path is not None else None
        )

    # --- Lifecycle ---

    def _ensure_dirs(self) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._user_data_dir.mkdir(parents=True, exist_ok=True)

    def _save_state(self, info: SessionInfo) -> None:
        self._ensure_dirs()
        self._state_file.write_text(info.model_dump_json())

    def _load_state(self) -> SessionInfo | None:
        if not self._state_file.exists():
            return None
        return SessionInfo.model_validate_json(self._state_file.read_text())

    def _clear_state(self) -> None:
        if self._state_file.exists():
            self._state_file.unlink()

    def _handle_from_state(self, info: SessionInfo) -> DriverHandle:
        return DriverHandle(
            driver=info.driver,
            pid=info.pid,
            endpoint=info.cdp_url or None,
            user_data_dir=info.user_data_dir,
            extra={"attached": "1"} if info.mode == "attached" else {},
        )

    def launch(self, url: str | None = None, headed: bool = True) -> SessionResult:
        """Launch the browser and connect."""
        self._ensure_dirs()
        logger.info("llm-browser session dir: %s", self.session_dir)
        handle = self.driver.launch(
            self._user_data_dir, url, headed, executable_path=self.executable_path
        )
        info = SessionInfo(
            pid=handle.pid,
            cdp_url=handle.endpoint or "",
            user_data_dir=handle.user_data_dir,
            driver=handle.driver,
            mode="launched",
        )
        self._save_state(info)
        self._page = self.driver.page(handle)
        screenshot = str(self.take_screenshot()) if url else None
        return SessionResult(
            status="open",
            url=self.driver.page_url(self._page) if self._page else None,
            screenshot=screenshot,
        )

    def attach(self, cdp_url: str) -> SessionResult:
        """Attach to an already-running Chromium exposing CDP at cdp_url.

        The remote browser is NOT killed on close(); only our connection and
        the tab we opened are cleaned up. Use this against a user-launched
        Chromium with a warmed profile to pass fingerprint-grade bot
        detection (Cloudflare, PerimeterX, DataDome).
        """
        self.session_dir.mkdir(parents=True, exist_ok=True)
        logger.info("llm-browser session dir: %s (attached)", self.session_dir)
        handle = self.driver.attach(cdp_url)
        info = SessionInfo(
            pid=None,
            cdp_url=handle.endpoint or cdp_url,
            user_data_dir=handle.user_data_dir,
            driver=handle.driver,
            mode="attached",
        )
        self._save_state(info)
        self._page = self.driver.page(handle)
        return SessionResult(
            status="open",
            url=self.driver.page_url(self._page) if self._page else None,
            cdp_url=cdp_url,
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
        self._ensure_dirs()
        resolved_profile = (
            Path(user_data_dir) if user_data_dir is not None else self._user_data_dir
        )
        resolved_exe = (
            str(executable_path)
            if executable_path is not None
            else self.executable_path
        )
        pid, cdp_url = spawn_detached_chromium(
            resolved_profile, headed=headed, executable_path=resolved_exe
        )
        logger.info(
            "llm-browser detached Chromium pid=%d cdp=%s profile=%s",
            pid,
            cdp_url,
            resolved_profile,
        )
        handle = self.driver.attach(cdp_url)
        info = SessionInfo(
            pid=pid,
            cdp_url=handle.endpoint or cdp_url,
            user_data_dir=str(resolved_profile),
            driver=handle.driver,
            mode="attached",
        )
        self._save_state(info)
        self._page = self.driver.page(handle)
        if url is not None:
            self.driver.goto(self._page, url, "domcontentloaded")
        return SessionResult(
            status="open",
            url=self.driver.page_url(self._page) if self._page else None,
            cdp_url=cdp_url,
        )

    def stop_detached(self) -> SessionResult:
        """Release our CDP connection AND kill the detached Chromium.

        Use this to shut down a browser previously started with
        ``launch_detached()``. A plain ``close()`` only releases the
        connection and leaves the browser running.
        """
        info = self._load_state()
        if info is not None:
            self.driver.close(self._handle_from_state(info))
            if info.pid:
                kill_detached_chromium(info.pid)
        self._page = None
        self._clear_state()
        return SessionResult(status="closed")

    def connect(self) -> Any:
        """Connect to a running browser and return the active page."""
        info = self._load_state()
        if info is None:
            raise RuntimeError("No browser session. Run 'llm-browser open' first.")
        if info.pid and not is_process_alive(info.pid):
            self._clear_state()
            raise RuntimeError(
                "Browser process is no longer running. Run 'llm-browser open' again."
            )
        self._page = self.driver.page(self._handle_from_state(info))
        return self._page

    def get_page(self) -> Any:
        """Get the current page, connecting if needed.

        Calls on the raw page/locator returned here BYPASS humanization —
        only actions routed through ``execute_action(...)`` honor
        ``Behavior.human()`` timing and mouse-path jitter.
        """
        if self._page is None:
            self.connect()
        assert self._page is not None
        return self._page

    def latest_tab(self) -> Any:
        """Switch to the most recently opened tab and return it."""
        info = self._load_state()
        if info is None:
            raise RuntimeError("No browser session.")
        if self._page is None:
            self._page = self.driver.page(self._handle_from_state(info))
        self._page = self.driver.latest_tab(self._handle_from_state(info))
        return self._page

    def close(self, cleanup: bool = False) -> SessionResult:
        """Close the browser and clean up.

        In attached mode, the remote Chromium process is NEVER killed —
        only our tab and the CDP connection are released.

        The user-data-dir is never auto-removed (profile reuse is intentional).
        Set ``cleanup=True`` to also delete screenshot.png and dom.html
        captured during this session.
        """
        info = self._load_state()
        if info is not None:
            self.driver.close(self._handle_from_state(info))
        self._page = None
        self._clear_state()
        if cleanup:
            for path in (self._screenshot_path, self._dom_path):
                if path.exists():
                    path.unlink()
        return SessionResult(status="closed")

    def status(self) -> SessionResult:
        """Return current browser status."""
        info = self._load_state()
        if info is None:
            return SessionResult(status="closed")
        if self.driver.status(self._handle_from_state(info)):
            return SessionResult(status="open", cdp_url=info.cdp_url or None)
        self._clear_state()
        return SessionResult(status="closed")

    def take_screenshot(self) -> Path:
        """Take a screenshot and return the file path."""
        self._ensure_dirs()
        self.driver.screenshot(self.get_page(), self._screenshot_path)
        return self._screenshot_path

    def take_dom_snapshot(self) -> Path:
        """Capture a sanitized HTML snapshot of the current page."""
        self._ensure_dirs()
        self._dom_path.write_text(
            sanitize_page_html(self.driver.content(self.get_page()))
        )
        return self._dom_path

    def download_file(self, selector: Selector, output_path: Path | str) -> Path:
        """Click element to trigger download and save to output_path."""
        output = prepare_output_path(output_path)
        element = self.find(selector)

        def trigger() -> None:
            self.driver.click(element)

        return self.driver.expect_download(self.get_page(), trigger, output)

    # --- Interaction ---

    def goto(self, url: str, wait_until: str = "domcontentloaded") -> None:
        self.driver.goto(self.get_page(), url, wait_until)

    def find(
        self, selector: Selector, state: str = "visible", timeout: int = 10_000
    ) -> Any:
        """Find exactly one element. Raises ValueError if multiple match."""
        locator = resolve_selector(self.driver, self.get_page(), selector)
        element = expect_single(self.driver, locator, selector)
        self.driver.wait_for_state(element, state, timeout)
        return element

    def find_all(
        self, selector: Selector, state: str = "attached", timeout: int = 10_000
    ) -> Any:
        """Find all matching elements, waiting for at least one."""
        locator = resolve_selector(self.driver, self.get_page(), selector)
        self.driver.wait_for_state(self.driver.first(locator), state, timeout)
        return locator

    def element_exists(self, selector: Selector, timeout: int = 3_000) -> bool:
        """Check if element is present. Never raises."""
        try:
            locator = resolve_selector(self.driver, self.get_page(), selector)
            self.driver.wait_for_state(self.driver.first(locator), "attached", timeout)
            return True
        except TimeoutError:
            return False

    def wait_until_stable(
        self,
        selector: Selector,
        quiet_ms: int = 1500,
        timeout_s: float = 180.0,
    ) -> str:
        """Wait until ``selector``'s textContent stops changing for ``quiet_ms``.

        Returns the final text. Raises ``TimeoutError`` on timeout. Designed
        for LLM chat UIs with token-streaming replies. On Playwright-family
        drivers the stability loop runs in-page (single CDP call); other
        drivers fall back to a Python poll.
        """
        element = self.find(selector)
        text = self.driver.wait_for_stable_text(
            element, quiet_ms=quiet_ms, timeout_ms=int(timeout_s * 1000)
        )
        if text is None:
            raise TimeoutError(
                f"wait_until_stable: {selector!r} did not stabilize within {timeout_s}s"
            )
        return text

    def wait_for_load_state(
        self, state: str = "domcontentloaded", timeout: int = 10_000
    ) -> None:
        """Wait for page load state (domcontentloaded, load, networkidle)."""
        self.driver.wait_for_load(self.get_page(), state, timeout)

    def pick(self, selector: Selector, value: str) -> None:
        """Click the element matching text from a list of elements."""
        locator = self.find_all(selector)
        count = self.driver.count(locator)
        if count == 1:
            self.driver.click(self.driver.first(locator))
            return
        for i in range(count):
            item = self.driver.nth(locator, i)
            if self.driver.text_content(item) == value:
                self.driver.click(item)
                return
        raise ValueError(f"No element with text '{value}' for selector {selector!r}")

    def frame(self, selector: Selector, timeout: int = 10_000) -> Any:
        """Enter an iframe, returning the Frame."""
        locator = resolve_selector(self.driver, self.get_page(), selector)
        element = expect_single(self.driver, locator, selector)
        self.driver.wait_for_state(element, "attached", timeout)
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
        results: list[dict[str, str | None]] = []
        locator = resolve_selector(self.driver, self.get_page(), selector)
        for row in self.driver.all(locator):
            record: dict[str, str | None] = {}
            for key, spec in extract.items():
                target = (
                    self.driver.child(row, spec.child_selector)
                    if spec.child_selector is not None
                    else row
                )
                match spec.attribute:
                    case "textContent":
                        record[key] = self.driver.text_content(target)
                    case "value":
                        record[key] = self.driver.input_value(target)
                    case _:
                        record[key] = self.driver.get_attribute(target, spec.attribute)
            results.append(record)
        return results

    def dom(self, selector: Selector, max_depth: int = 0) -> str:
        """Return cleaned HTML snippet of an element."""
        from llm_browser.html import sanitize_html_fragment

        raw: str = self.driver.evaluate(self.find(selector), "el => el.outerHTML")
        return sanitize_html_fragment(raw, max_depth)

    def evaluate(self, target: Any, script: str) -> Any:
        """Run JS in the context of a page or locator."""
        return self.driver.evaluate(target, script)
