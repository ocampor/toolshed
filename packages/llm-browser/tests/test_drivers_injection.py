"""Plug-and-play contract: BrowserSession routes through an injected Driver."""

from pathlib import Path
from typing import Any, Callable, ClassVar
from unittest.mock import MagicMock

from llm_browser.drivers.base import Driver, DriverHandle
from llm_browser.session import BrowserSession


class FakeDriver(Driver):
    name: ClassVar[str] = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._page = MagicMock()
        self._locator = MagicMock()
        self._locator.count.return_value = 1

    def _record(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))

    def launch(
        self,
        user_data_dir: Path,
        url: str | None,
        headed: bool,
        executable_path: str | None = None,
    ) -> DriverHandle:
        self._record("launch", user_data_dir, url, headed, executable_path)
        return DriverHandle(driver=self.name, user_data_dir=str(user_data_dir), pid=1)

    def page(self, handle: DriverHandle) -> Any:
        self._record("page", handle)
        return self._page

    def close(self, handle: DriverHandle) -> None:
        self._record("close", handle)

    def status(self, handle: DriverHandle) -> bool:
        self._record("status", handle)
        return True

    def latest_tab(self, handle: DriverHandle) -> Any:
        self._record("latest_tab", handle)
        return self._page

    def resolve(self, page: Any, selector: str) -> Any:
        self._record("resolve", page, selector)
        return self._locator

    def click(self, locator: Any, *, dispatch: bool = False) -> None:
        self._record("click", locator, dispatch)

    def fill(self, locator: Any, text: str) -> None:
        self._record("fill", locator, text)

    def type(self, locator: Any, text: str, *, delay_ms: int = 0) -> None:
        self._record("type", locator, text, delay_ms)

    def press(self, locator: Any, key: str) -> None:
        self._record("press", locator, key)

    def press_focused(self, page: Any, key: str) -> None:
        self._record("press_focused", page, key)

    def select_option(self, locator: Any, value: str) -> None:
        self._record("select_option", value)

    def set_checked(self, locator: Any, checked: bool) -> None:
        self._record("set_checked", checked)

    def dispatch_event(self, locator: Any, event: str) -> None:
        self._record("dispatch_event", event)

    def goto(self, page: Any, url: str, wait_until: str) -> None:
        self._record("goto", url, wait_until)

    def wait_for_load(self, page: Any, state: str, timeout_ms: int) -> None:
        self._record("wait_for_load", state, timeout_ms)

    def wait_for_state(self, locator: Any, state: str, timeout_ms: int) -> None:
        self._record("wait_for_state", state, timeout_ms)

    def text_content(self, locator: Any) -> str | None:
        return "txt"

    def input_value(self, locator: Any) -> str:
        return "val"

    def get_attribute(self, locator: Any, name: str) -> str | None:
        return "attr"

    def count(self, locator: Any) -> int:
        return 1

    def first(self, locator: Any) -> Any:
        return locator

    def nth(self, locator: Any, index: int) -> Any:
        return locator

    def all(self, locator: Any) -> list[Any]:
        return [locator]

    def child(self, locator: Any, selector: str) -> Any:
        return locator

    def evaluate(self, target: Any, script: str) -> Any:
        return "<html></html>"

    def content(self, page: Any) -> str:
        return "<html></html>"

    def page_url(self, page: Any) -> str:
        return "https://example.com"

    def screenshot(self, page: Any, path: Path) -> None:
        path.write_bytes(b"png")

    def expect_download(
        self, page: Any, trigger: Callable[[], None], output: Path
    ) -> Path:
        trigger()
        output.write_bytes(b"download")
        return output

    def enter_frame(self, locator: Any) -> Any:
        return self._page


def test_launch_routes_to_driver(tmp_path: Path) -> None:
    driver = FakeDriver()
    session = BrowserSession(session_id="test", state_dir=tmp_path, driver=driver)
    result = session.launch(url="https://example.com", headed=False)
    assert result.status == "open"
    assert any(c[0] == "launch" for c in driver.calls)
    assert any(c[0] == "page" for c in driver.calls)


def test_goto_routes_to_driver(tmp_path: Path) -> None:
    driver = FakeDriver()
    session = BrowserSession(session_id="test", state_dir=tmp_path, driver=driver)
    session.launch(headed=False)
    session.goto("https://example.com")
    assert any(c[0] == "goto" for c in driver.calls)


def test_find_uses_driver_resolve(tmp_path: Path) -> None:
    driver = FakeDriver()
    session = BrowserSession(session_id="test", state_dir=tmp_path, driver=driver)
    session.launch(headed=False)
    session.find("#btn")
    assert any(c[0] == "resolve" for c in driver.calls)
    assert any(c[0] == "wait_for_state" for c in driver.calls)


def test_string_driver_resolves_to_patchright(tmp_path: Path) -> None:
    from llm_browser.drivers import PatchrightDriver

    session = BrowserSession(session_id="test", state_dir=tmp_path, driver="patchright")
    assert isinstance(session.driver, PatchrightDriver)
