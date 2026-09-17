"""A failed launch/attach must not leave patchright's event loop running."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from llm_browser.drivers.patchright import PatchrightDriver

CDP_URL = "http://127.0.0.1:9223"
BOOM = RuntimeError("no chromium here")


@pytest.fixture
def playwright(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The Playwright ``start_playwright()`` hands the driver."""
    pw = MagicMock()
    monkeypatch.setattr(
        "llm_browser.drivers.patchright.start_playwright",
        lambda: pw,
    )
    return pw


def break_launch(playwright: Any) -> None:
    playwright.chromium.launch_persistent_context.side_effect = BOOM


def break_goto(playwright: Any) -> None:
    context = playwright.chromium.launch_persistent_context.return_value
    context.pages = [MagicMock()]
    context.pages[0].goto.side_effect = BOOM


@pytest.mark.parametrize("break_step", [break_launch, break_goto])
def test_failed_launch_stops_the_playwright_it_started(
    playwright: Any, tmp_path: Path, break_step: Any
) -> None:
    break_step(playwright)
    driver = PatchrightDriver()

    with pytest.raises(RuntimeError, match="no chromium here"):
        driver.launch(tmp_path / "profile", "https://example.com", headed=False)

    playwright.stop.assert_called_once_with()
    assert driver._playwright is None


def test_failed_attach_stops_the_playwright_it_started(playwright: Any) -> None:
    playwright.chromium.connect_over_cdp.side_effect = BOOM
    driver = PatchrightDriver()

    with pytest.raises(RuntimeError, match="no chromium here"):
        driver.attach(CDP_URL)

    playwright.stop.assert_called_once_with()
    assert driver._playwright is None


def test_failed_attach_keeps_a_playwright_it_did_not_start(playwright: Any) -> None:
    """A retry on a live driver must not stop the connection an earlier call owns."""
    playwright.chromium.connect_over_cdp.side_effect = BOOM
    driver = PatchrightDriver()
    driver._playwright = playwright

    with pytest.raises(RuntimeError, match="no chromium here"):
        driver.attach(CDP_URL)

    playwright.stop.assert_not_called()
    assert driver._playwright is playwright
