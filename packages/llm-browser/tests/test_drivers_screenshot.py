"""Tests for in-memory screenshots across the driver layer."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from llm_browser.drivers.patchright import PatchrightDriver
from tests.test_drivers_injection import FakeDriver

PNG = b"\x89PNG\r\n\x1a\nfake"


class FileOnlyScreenshotDriver(FakeDriver):
    """Driver whose screenshot API can only write a file — the base fallback case."""

    def __init__(self) -> None:
        super().__init__()
        self.paths: list[Path] = []

    def screenshot(self, page: Any, path: Path) -> None:
        self.paths.append(path)
        path.write_bytes(PNG)


def test_base_fallback_returns_file_bytes() -> None:
    assert FileOnlyScreenshotDriver().screenshot_bytes(MagicMock()) == PNG


def test_base_fallback_removes_temp_file() -> None:
    driver = FileOnlyScreenshotDriver()
    driver.screenshot_bytes(MagicMock())
    assert len(driver.paths) == 1
    assert not driver.paths[0].exists()


def test_playwright_returns_bytes_without_writing_a_file() -> None:
    page = MagicMock()
    page.screenshot.return_value = PNG
    assert PatchrightDriver().screenshot_bytes(page) == PNG
    page.screenshot.assert_called_once_with(full_page=False)


def test_playwright_file_screenshot_still_writes(tmp_path: Path) -> None:
    page = MagicMock()
    target = tmp_path / "shot.png"
    PatchrightDriver().screenshot(page, target)
    page.screenshot.assert_called_once_with(path=str(target), full_page=False)


def test_nodriver_asks_for_png() -> None:
    """nodriver's `save_screenshot` defaults to jpeg, so it would write JPEG
    bytes into the `.png` file every caller above it asks for."""
    import asyncio

    from llm_browser.drivers.nodriver import NodriverDriver

    page = MagicMock()

    async def save_screenshot(**kwargs: Any) -> str:
        page.saved = kwargs
        return kwargs["filename"]

    page.save_screenshot = save_screenshot
    driver = NodriverDriver()
    driver.loop = asyncio.new_event_loop()
    driver.screenshot(page, Path("/tmp/shot.png"))
    assert page.saved == {"filename": "/tmp/shot.png", "format": "png"}
