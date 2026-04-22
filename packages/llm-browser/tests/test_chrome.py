"""Tests for chrome.py executable discovery."""

from unittest.mock import patch

import pytest

from llm_browser.chrome import ChromiumNotInstalledError, chromium_executable


def test_chromium_executable_missing_raises_actionable() -> None:
    with patch("llm_browser.chrome.sync_playwright") as sp:
        sp.return_value.start.side_effect = RuntimeError("no bundled browser")
        with pytest.raises(
            ChromiumNotInstalledError, match="patchright install chromium"
        ):
            chromium_executable()


def test_chromium_executable_nonexistent_path_raises() -> None:
    fake_pw = type("Pw", (), {})()
    fake_pw.chromium = type("C", (), {"executable_path": "/does/not/exist"})()
    fake_pw.stop = lambda: None
    with patch("llm_browser.chrome.sync_playwright") as sp:
        sp.return_value.start.return_value = fake_pw
        with pytest.raises(ChromiumNotInstalledError, match="does not exist"):
            chromium_executable()
