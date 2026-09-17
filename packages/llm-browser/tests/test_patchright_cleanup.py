"""A failed launch/attach must leave neither an event loop nor stale objects."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from llm_browser.drivers.handle import DriverHandle
from llm_browser.drivers.patchright import PatchrightDriver

CDP_URL = "http://127.0.0.1:9223"
BOOM = RuntimeError("no chromium here")
ATTACHED_HANDLE = DriverHandle(
    driver="patchright",
    endpoint=CDP_URL,
    user_data_dir="",
    extra={"attached": "1", "target_id": "T1"},
)
LAUNCHED_HANDLE = DriverHandle(driver="patchright", user_data_dir="/tmp/profile")


@pytest.fixture
def playwright(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The Playwright ``start_playwright()`` hands the driver."""
    pw = MagicMock()
    monkeypatch.setattr(
        "llm_browser.drivers.patchright.start_playwright",
        lambda: pw,
    )
    return pw


def assert_no_live_state(driver: PatchrightDriver) -> None:
    assert driver._playwright is None
    assert driver._browser is None
    assert driver._context is None
    assert driver._page is None


def break_launch(playwright: Any) -> None:
    playwright.chromium.launch_persistent_context.side_effect = BOOM


def break_goto(playwright: Any) -> None:
    context = playwright.chromium.launch_persistent_context.return_value
    context.pages = [MagicMock()]
    context.pages[0].goto.side_effect = BOOM
    # A context whose connection died raises on close, like a real one.
    context.close.side_effect = RuntimeError("target closed")


def break_new_page(playwright: Any) -> None:
    browser = playwright.chromium.connect_over_cdp.return_value
    browser.contexts = [MagicMock()]
    browser.contexts[0].new_page.side_effect = BOOM


def launch(driver: PatchrightDriver) -> None:
    driver.launch(Path("/tmp/profile"), "https://example.com", headed=False)


def attach(driver: PatchrightDriver) -> None:
    driver.attach(CDP_URL)


def attach_to_tab(driver: PatchrightDriver) -> None:
    driver.attach_to_tab(CDP_URL, "T1")


def reattach(driver: PatchrightDriver) -> None:
    driver._reattach_or_raise(ATTACHED_HANDLE)


@pytest.mark.parametrize("break_step", [break_launch, break_goto])
def test_failed_launch_leaves_no_live_state(
    playwright: Any, tmp_path: Path, break_step: Any
) -> None:
    break_step(playwright)
    driver = PatchrightDriver()

    with pytest.raises(RuntimeError, match="no chromium here"):
        driver.launch(tmp_path / "profile", "https://example.com", headed=False)

    playwright.stop.assert_called_once_with()
    assert_no_live_state(driver)


@pytest.mark.parametrize("entry_point", [attach, attach_to_tab, reattach])
def test_failed_attach_leaves_no_live_state(playwright: Any, entry_point: Any) -> None:
    # These never reach the rollback's state-clearing: connect_over_cdp raises
    # before anything is assigned. test_attach_after_a_failed_attach_opens_a_
    # fresh_connection is what actually bites when that clearing goes missing.
    playwright.chromium.connect_over_cdp.side_effect = BOOM
    driver = PatchrightDriver()

    with pytest.raises(RuntimeError, match="no chromium here"):
        entry_point(driver)

    playwright.stop.assert_called_once_with()
    assert_no_live_state(driver)


@pytest.mark.parametrize("entry_point", [attach, attach_to_tab, reattach])
def test_failed_attach_keeps_a_playwright_it_did_not_start(
    playwright: Any, entry_point: Any
) -> None:
    """A retry on a live driver must not stop the connection an earlier call owns."""
    playwright.chromium.connect_over_cdp.side_effect = BOOM
    driver = PatchrightDriver()
    driver._playwright = playwright

    with pytest.raises(RuntimeError, match="no chromium here"):
        entry_point(driver)

    playwright.stop.assert_not_called()
    assert driver._playwright is playwright


def test_close_after_a_failed_launch_does_not_raise(
    playwright: Any, tmp_path: Path
) -> None:
    break_goto(playwright)
    driver = PatchrightDriver()

    with pytest.raises(RuntimeError, match="no chromium here"):
        driver.launch(tmp_path / "profile", "https://example.com", headed=False)

    driver.close(LAUNCHED_HANDLE)


def test_attach_after_a_failed_attach_opens_a_fresh_connection(
    playwright: Any,
) -> None:
    """The stale browser reports itself connected, so it must not be reused."""
    break_new_page(playwright)
    driver = PatchrightDriver()

    with pytest.raises(RuntimeError, match="no chromium here"):
        driver.attach(CDP_URL)

    playwright.chromium.connect_over_cdp.return_value.contexts[
        0
    ].new_page.side_effect = None
    driver.attach(CDP_URL)

    assert playwright.chromium.connect_over_cdp.call_count == 2
