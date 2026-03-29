"""Browser session: CDP connection, page management, state persistence."""

from pathlib import Path

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from llm_browser.chrome import is_process_alive, kill_chrome, launch_chrome
from llm_browser.constants import DEFAULT_STATE_DIR
from llm_browser.models import SessionInfo, SessionResult


class BrowserSession:
    """Manages a persistent Chrome browser via CDP.

    Each session has its own directory under state_dir/sessions/{session_id}/
    containing the state file, screenshots, user data, and flow state.
    """

    def __init__(
        self,
        session_id: str = "default",
        state_dir: Path = DEFAULT_STATE_DIR,
    ) -> None:
        self.session_dir = state_dir / "sessions" / session_id
        self._state_file = self.session_dir / "state.json"
        self._user_data_dir = self.session_dir / "user-data"
        self._screenshot_path = self.session_dir / "screenshot.png"
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None

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
            pid=pid,
            cdp_url=cdp_url,
            user_data_dir=str(self._user_data_dir),
        )
        self._save_state(info)

        page = self.connect()
        screenshot = str(self.take_screenshot()) if url else None

        return SessionResult(status="open", url=page.url, screenshot=screenshot)

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
        """Get the current page, connecting via CDP if needed."""
        if self._page is None:
            self.connect()
        assert self._page is not None
        return self._page

    def take_screenshot(self) -> Path:
        """Take a screenshot and return the file path."""
        self._ensure_dirs()
        page = self.get_page()
        page.screenshot(path=str(self._screenshot_path), full_page=False)
        return self._screenshot_path

    def evaluate_js(self, js: str) -> object:
        """Evaluate JavaScript on the current page."""
        return self.get_page().evaluate(js)

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
