"""Tests for BrowserSession.attach() CDP-attach mode."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from llm_browser.drivers.base import Driver, DriverHandle
from llm_browser.session import BrowserSession


class AttachStubDriver(Driver):
    """Minimal stub that records attach/close and never touches a PID."""

    name = "stub"

    def __init__(self) -> None:
        self.attach_calls: list[str] = []
        self.close_calls: list[DriverHandle] = []
        self._page = MagicMock()

    def launch(
        self,
        user_data_dir: Path,
        url: str | None,
        headed: bool,
        executable_path: str | None = None,
    ) -> DriverHandle:
        raise NotImplementedError

    def attach(self, cdp_url: str) -> DriverHandle:
        self.attach_calls.append(cdp_url)
        return DriverHandle(
            driver=self.name,
            pid=None,
            endpoint=cdp_url,
            user_data_dir="",
            extra={"attached": "1"},
        )

    def page(self, handle: DriverHandle) -> Any:
        return self._page

    def close(self, handle: DriverHandle) -> None:
        self.close_calls.append(handle)

    def status(self, handle: DriverHandle) -> bool:
        return True

    def latest_tab(self, handle: DriverHandle) -> Any:
        return self._page

    def resolve(self, page: Any, selector: str) -> Any:
        return MagicMock()

    def click(self, locator: Any, *, dispatch: bool = False) -> None: ...
    def fill(self, locator: Any, text: str) -> None: ...
    def type(self, locator: Any, text: str, *, delay_ms: int = 0) -> None: ...
    def press(self, locator: Any, key: str) -> None: ...
    def press_focused(self, page: Any, key: str) -> None: ...
    def select_option(self, locator: Any, value: str) -> None: ...
    def set_checked(self, locator: Any, checked: bool) -> None: ...
    def dispatch_event(self, locator: Any, event: str) -> None: ...
    def goto(self, page: Any, url: str, wait_until: str) -> None: ...
    def wait_for_load(self, page: Any, state: str, timeout_ms: int) -> None: ...
    def wait_for_state(self, locator: Any, state: str, timeout_ms: int) -> None: ...
    def text_content(self, locator: Any) -> str | None:
        return None

    def input_value(self, locator: Any) -> str:
        return ""

    def get_attribute(self, locator: Any, name: str) -> str | None:
        return None

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
        return None

    def content(self, page: Any) -> str:
        return ""

    def page_url(self, page: Any) -> str:
        return "about:blank"

    def screenshot(self, page: Any, path: Path) -> None: ...

    def expect_download(self, page: Any, trigger: Any, output: Path) -> Path:
        return output

    def enter_frame(self, locator: Any) -> Any:
        return MagicMock()


def test_attach_persists_attached_mode(tmp_path: Path) -> None:
    driver = AttachStubDriver()
    session = BrowserSession(state_dir=tmp_path, driver=driver)
    session.attach("http://localhost:9222")

    info = session._load_state()
    assert info is not None
    assert info.mode == "attached"
    assert info.pid is None
    assert info.cdp_url == "http://localhost:9222"
    assert driver.attach_calls == ["http://localhost:9222"]


def test_attach_close_never_kills_pid(tmp_path: Path) -> None:
    driver = AttachStubDriver()
    session = BrowserSession(state_dir=tmp_path, driver=driver)
    session.attach("http://localhost:9222")
    session.close()

    assert len(driver.close_calls) == 1
    handle = driver.close_calls[0]
    assert handle.pid is None
    assert handle.extra.get("attached") == "1"


def test_attach_close_cleanup_removes_capture_files(tmp_path: Path) -> None:
    driver = AttachStubDriver()
    session = BrowserSession(state_dir=tmp_path, driver=driver)
    session.attach("http://localhost:9222")
    session._screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    session._screenshot_path.write_text("x")
    session._dom_path.write_text("y")
    session.close(cleanup=True)
    assert not session._screenshot_path.exists()
    assert not session._dom_path.exists()


def test_default_wait_for_stable_text_returns_none_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Driver's Python-side fallback returns None when text keeps changing."""
    monkeypatch.setattr("time.sleep", lambda *_: None)
    driver = AttachStubDriver()
    counter = {"n": 0}

    def never_stable(locator: Any) -> str:
        counter["n"] += 1
        return str(counter["n"])

    driver.text_content = never_stable  # type: ignore[method-assign]
    assert driver.wait_for_stable_text(MagicMock(), quiet_ms=1000, timeout_ms=5) is None


def test_default_wait_for_stable_text_returns_stable_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("time.sleep", lambda *_: None)
    driver = AttachStubDriver()

    def _stable(_loc: Any) -> str | None:
        return "settled"

    driver.text_content = _stable  # type: ignore[method-assign,assignment]
    assert (
        driver.wait_for_stable_text(MagicMock(), quiet_ms=1, timeout_ms=500)
        == "settled"
    )


def test_patchright_reattaches_from_cdp_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh PatchrightDriver with an attached-mode handle reconnects via CDP."""
    from llm_browser.drivers.patchright import PatchrightDriver

    fake_page = MagicMock()
    fake_context = MagicMock()
    fake_context.pages = [fake_page]
    fake_browser = MagicMock()
    fake_browser.contexts = [fake_context]
    fake_pw = MagicMock()
    fake_pw.chromium.connect_over_cdp.return_value = fake_browser

    monkeypatch.setattr(
        "llm_browser.drivers.patchright.sync_playwright",
        lambda: MagicMock(start=lambda: fake_pw),
    )

    driver = PatchrightDriver()
    handle = DriverHandle(
        driver="patchright",
        pid=None,
        endpoint="http://localhost:9222",
        user_data_dir="",
        extra={"attached": "1"},
    )
    page = driver.page(handle)
    assert page is fake_page
    fake_pw.chromium.connect_over_cdp.assert_called_once_with("http://localhost:9222")


def test_patchright_launched_mode_does_not_reattach() -> None:
    """Launched mode can't recover from a fresh process — raises a clear error."""
    from llm_browser.drivers.patchright import PatchrightDriver

    driver = PatchrightDriver()
    handle = DriverHandle(driver="patchright", user_data_dir="/tmp/x")
    with pytest.raises(RuntimeError, match="launched mode does not survive"):
        driver.page(handle)


def test_patchright_status_true_when_attached_and_endpoint_set() -> None:
    """status() reports open for a fresh attach-mode handle, enabling CLI reuse."""
    from llm_browser.drivers.patchright import PatchrightDriver

    driver = PatchrightDriver()
    attached = DriverHandle(
        driver="patchright",
        endpoint="http://localhost:9222",
        user_data_dir="",
        extra={"attached": "1"},
    )
    launched = DriverHandle(driver="patchright", user_data_dir="/tmp/x")
    assert driver.status(attached) is True
    assert driver.status(launched) is False


def test_base_driver_attach_raises() -> None:
    """Drivers that don't override attach() should raise NotImplementedError."""

    class NoAttach(AttachStubDriver):
        def attach(self, cdp_url: str) -> DriverHandle:
            return Driver.attach(self, cdp_url)

    with pytest.raises(NotImplementedError):
        NoAttach().attach("ws://x")
