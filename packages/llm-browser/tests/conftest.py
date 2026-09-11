from pathlib import Path
from unittest.mock import MagicMock

import pytest

from llm_browser.behavior import Behavior
from llm_browser.models import PageProbe
from llm_browser.results import BytesResult
from llm_browser.session import BrowserSession

PNG = b"\x89PNG\r\n\x1a\nfake"


@pytest.fixture
def mock_session(tmp_path: Path) -> MagicMock:
    session = MagicMock(spec=BrowserSession)
    session.session_dir = tmp_path
    session.behavior = Behavior.off()
    session.behavior_runtime = session.behavior.runtime()
    session.capture = "screenshot"
    session.driver = MagicMock()
    session.get_page.return_value = MagicMock()
    session.take_screenshot.return_value = tmp_path / "screenshot.png"
    session.screenshot_bytes.return_value = PNG
    session.download_file.return_value = BytesResult(
        name="download.bin", content=b"payload"
    )
    session.element_exists.return_value = True
    session.probe.return_value = PageProbe()
    locator = MagicMock()
    locator.count.return_value = 1
    session.find.return_value = locator
    session.find_all.return_value = locator
    session.parse_elements.return_value = [{"title": "hello"}]
    session.dom.return_value = "<p>hello</p>"
    return session
