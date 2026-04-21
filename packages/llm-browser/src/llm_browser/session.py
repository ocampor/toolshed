"""BrowserSession: browser lifecycle + direct interaction API."""

from pathlib import Path

from patchright.sync_api import Browser, Locator, Page, Playwright, sync_playwright

from llm_browser.behavior import Behavior, BehaviorRuntime
from llm_browser.chrome import is_process_alive, kill_chrome, launch_chrome
from llm_browser.constants import DEFAULT_STATE_DIR
from llm_browser.models import SessionInfo, SessionResult
from llm_browser.selectors import PageLike, Selector, expect_single, resolve_selector


class BrowserSession:
    """Browser lifecycle management + page interaction API.

    Each instance manages a persistent Chrome session via CDP and
    provides high-level methods for page interaction.
    """

    def __init__(
        self,
        session_id: str = "default",
        state_dir: Path = DEFAULT_STATE_DIR,
        behavior: Behavior | None = None,
    ) -> None:
        self.session_dir = state_dir / "sessions" / session_id
        self._state_file = self.session_dir / "state.json"
        self._user_data_dir = self.session_dir / "user-data"
        self._screenshot_path = self.session_dir / "screenshot.png"
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None
        self.behavior: Behavior = behavior if behavior is not None else Behavior.off()
        self._behavior_runtime: BehaviorRuntime = self.behavior.runtime()

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

    def launch(self, url: str | None = None, headed: bool = True) -> SessionResult:
        """Launch Chrome as a background process and connect via CDP."""
        self._ensure_dirs()
        pid, cdp_url = launch_chrome(self._user_data_dir, url, headed)
        info = SessionInfo(
            pid=pid, cdp_url=cdp_url, user_data_dir=str(self._user_data_dir)
        )
        self._save_state(info)
        self.connect()
        screenshot = str(self.take_screenshot()) if url else None
        return SessionResult(
            status="open",
            url=self._page.url,  # type: ignore[union-attr]
            screenshot=screenshot,
        )

    def connect(self) -> Page:
        """Connect to a running Chrome via CDP and return the active page."""
        info = self._load_state()
        if info is None:
            raise RuntimeError("No browser session. Run 'llm-browser open' first.")
        if not is_process_alive(info.pid):
            self._clear_state()
            raise RuntimeError(
                "Browser process is no longer running. Run 'llm-browser open' again."
            )
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.connect_over_cdp(info.cdp_url)
        contexts = self._browser.contexts
        if contexts and contexts[0].pages:
            self._page = contexts[0].pages[-1]
        else:
            ctx = contexts[0] if contexts else self._browser.new_context()
            self._page = ctx.new_page()
        return self._page

    def get_page(self) -> Page:
        """Get the current Playwright page, connecting if needed."""
        if self._page is None:
            self.connect()
        assert self._page is not None
        return self._page

    def latest_tab(self) -> Page:
        """Switch to the most recently opened tab and return it."""
        if self._browser is None:
            self.connect()
        assert self._browser is not None
        contexts = self._browser.contexts
        if not contexts or not contexts[0].pages:
            raise RuntimeError("No tabs open.")
        self._page = contexts[0].pages[-1]
        return self._page

    def close(self) -> SessionResult:
        """Kill the Chrome process and clean up."""
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._pw is not None:
            self._pw.stop()
            self._pw = None
        self._page = None
        info = self._load_state()
        if info is not None:
            kill_chrome(info.pid)
        self._clear_state()
        return SessionResult(status="closed")

    def status(self) -> SessionResult:
        """Return current browser status."""
        info = self._load_state()
        if info is None:
            return SessionResult(status="closed")
        if is_process_alive(info.pid):
            return SessionResult(status="open", cdp_url=info.cdp_url)
        self._clear_state()
        return SessionResult(status="closed")

    def take_screenshot(self) -> Path:
        """Take a screenshot and return the file path."""
        self._ensure_dirs()
        self.get_page().screenshot(path=str(self._screenshot_path), full_page=False)
        return self._screenshot_path

    def download_file(self, selector: Selector, output_path: Path | str) -> Path:
        """Click element to trigger download and save to output_path."""
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with self.get_page().expect_download() as download_info:
            self.find(selector).click()
        download_info.value.save_as(str(output))
        return output

    # --- Interaction ---

    def goto(self, url: str, wait_until: str = "domcontentloaded") -> None:
        self.get_page().goto(url, wait_until=wait_until)  # type: ignore[arg-type]

    def find(
        self, selector: Selector, state: str = "visible", timeout: int = 10_000
    ) -> Locator:
        """Find exactly one element. Raises ValueError if multiple match."""
        element = expect_single(resolve_selector(self.get_page(), selector), selector)
        element.wait_for(state=state, timeout=timeout)  # type: ignore[arg-type]
        return element

    def find_all(
        self, selector: Selector, state: str = "attached", timeout: int = 10_000
    ) -> Locator:
        """Find all matching elements, waiting for at least one."""
        locator = resolve_selector(self.get_page(), selector)
        locator.first.wait_for(state=state, timeout=timeout)  # type: ignore[arg-type]
        return locator

    def element_exists(self, selector: Selector, timeout: int = 3_000) -> bool:
        """Check if element is present. Never raises."""
        try:
            locator = resolve_selector(self.get_page(), selector)
            locator.first.wait_for(state="attached", timeout=timeout)
            return True
        except TimeoutError:
            return False

    def wait_for_load_state(
        self, state: str = "domcontentloaded", timeout: int = 10_000
    ) -> None:
        """Wait for page load state (domcontentloaded, load, networkidle)."""
        self.get_page().wait_for_load_state(state, timeout=timeout)  # type: ignore[arg-type]

    def pick(self, selector: Selector, value: str) -> None:
        """Click the element matching text from a list of elements."""
        locator = self.find_all(selector)
        count = locator.count()
        if count == 1:
            locator.first.click()
            return
        for i in range(count):
            if locator.nth(i).text_content() == value:
                locator.nth(i).click()
                return
        raise ValueError(f"No element with text '{value}' for selector {selector!r}")

    def frame(self, selector: Selector, timeout: int = 10_000) -> PageLike:
        """Enter an iframe, returning the Frame."""
        element = expect_single(resolve_selector(self.get_page(), selector), selector)
        element.wait_for(state="attached", timeout=timeout)
        handle = element.element_handle()
        if handle is None:
            raise RuntimeError(f"Could not get handle for selector {selector}")
        content_frame = handle.content_frame()
        if content_frame is None:
            raise RuntimeError(f"Could not find frame for selector {selector}")
        return content_frame

    def parse_elements(
        self,
        selector: Selector,
        extract: dict[str, dict[str, str]],
    ) -> list[dict[str, str | None]]:
        """Extract structured data from matching elements."""
        results: list[dict[str, str | None]] = []
        for row in resolve_selector(self.get_page(), selector).all():
            record: dict[str, str | None] = {}
            for key, spec in extract.items():
                child = row.locator(spec["child_selector"])
                attr = spec.get("attribute", "textContent")
                match attr:
                    case "textContent":
                        record[key] = child.text_content()
                    case "value":
                        record[key] = child.input_value()
                    case _:
                        record[key] = child.get_attribute(attr)
            results.append(record)
        return results

    def dom(self, selector: Selector, max_depth: int = 0) -> str:
        """Return cleaned HTML snippet of an element."""
        from llm_browser.html import clean_html

        raw: str = self.find(selector).evaluate("el => el.outerHTML")
        return clean_html(raw, max_depth)
