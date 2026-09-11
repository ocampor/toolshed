"""Tests for in-memory screenshots across the driver layer."""

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from llm_browser.drivers.nodriver import NodriverDriver
from llm_browser.drivers.patchright import PatchrightDriver

PNG = b"\x89PNG\r\n\x1a\nfake"


def test_playwright_returns_bytes_without_writing_a_file() -> None:
    page = MagicMock()
    page.screenshot.return_value = PNG
    assert PatchrightDriver().screenshot_bytes(page) == PNG
    page.screenshot.assert_called_once_with(full_page=False)


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
