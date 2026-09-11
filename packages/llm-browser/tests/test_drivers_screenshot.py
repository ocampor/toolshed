"""Tests for in-memory screenshots across the driver layer."""

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from llm_browser.drivers.base import Driver
from llm_browser.drivers.nodriver import NodriverDriver, NodriverLocator
from llm_browser.drivers.patchright import PatchrightDriver

PNG = b"\x89PNG\r\n\x1a\nfake"


def test_playwright_returns_bytes_without_writing_a_file() -> None:
    page = MagicMock()
    page.screenshot.return_value = PNG
    assert PatchrightDriver().screenshot_bytes(page) == PNG
    page.screenshot.assert_called_once_with(full_page=False)


def test_playwright_crops_to_the_element_it_was_handed() -> None:
    locator = MagicMock()
    locator.screenshot.return_value = PNG
    assert PatchrightDriver().screenshot_element_bytes(locator) == PNG
    locator.screenshot.assert_called_once_with()


def _nodriver_page() -> tuple[NodriverDriver, MagicMock]:
    """nodriver can only capture to a file, so the fake writes one."""
    page = MagicMock()
    page.spooled = []

    async def save_screenshot(**kwargs: Any) -> str:
        page.saved = kwargs
        page.spooled.append(Path(kwargs["filename"]))
        Path(kwargs["filename"]).write_bytes(PNG)
        return kwargs["filename"]

    async def activate() -> None:
        return None

    page.save_screenshot = save_screenshot
    page.activate = activate
    driver = NodriverDriver()
    driver.loop = asyncio.new_event_loop()
    return driver, page


def test_nodriver_reads_back_its_spooled_capture() -> None:
    driver, page = _nodriver_page()
    assert driver.screenshot_bytes(page) == PNG


def test_nodriver_removes_the_spool_file() -> None:
    driver, page = _nodriver_page()
    driver.screenshot_bytes(page)
    assert page.spooled and not page.spooled[0].exists()


def test_nodriver_asks_for_png() -> None:
    """nodriver's `save_screenshot` defaults to jpeg, so it would hand back
    JPEG bytes from the `.png` file every caller here asks for."""
    driver, page = _nodriver_page()
    driver.screenshot_bytes(page)
    assert page.saved["format"] == "png"


def _nodriver_element() -> tuple[NodriverDriver, MagicMock, NodriverLocator]:
    """nodriver captures an element to a file too, so the fake writes one."""
    element = MagicMock()
    element.spooled = []

    async def save_screenshot(**kwargs: Any) -> str:
        element.saved = kwargs
        element.spooled.append(Path(kwargs["filename"]))
        Path(kwargs["filename"]).write_bytes(PNG)
        return kwargs["filename"]

    element.save_screenshot = save_screenshot
    driver = NodriverDriver()
    driver.loop = asyncio.new_event_loop()
    return driver, element, NodriverLocator(tab=MagicMock(), element=element)


def test_nodriver_reads_back_its_spooled_element_capture() -> None:
    driver, element, locator = _nodriver_element()
    assert driver.screenshot_element_bytes(locator) == PNG
    assert element.saved["format"] == "png"
    assert element.spooled and not element.spooled[0].exists()


def test_nodriver_element_capture_fails_the_step_when_nothing_matches() -> None:
    driver = NodriverDriver()
    driver.loop = asyncio.new_event_loop()
    tab = MagicMock()

    async def select(selector: str) -> None:
        return None

    tab.select = select
    locator = NodriverLocator(tab=tab, selector="#gone")

    with pytest.raises(ValueError, match="#gone"):
        driver.screenshot_element_bytes(locator)


def test_a_driver_without_element_capture_reports_it_as_unsupported() -> None:
    """The contract's opt-out: `NotImplementedError` is a conformance skip."""
    with pytest.raises(NotImplementedError, match="element screenshots"):
        Driver.screenshot_element_bytes(MagicMock(spec=Driver), MagicMock())
