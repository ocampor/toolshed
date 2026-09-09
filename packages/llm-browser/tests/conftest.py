from pathlib import Path
from unittest.mock import MagicMock

import pytest

from llm_browser.behavior import Behavior
from llm_browser.session import BrowserSession


@pytest.fixture
def mock_session(tmp_path: Path) -> MagicMock:
    session = MagicMock(spec=BrowserSession)
    session.session_dir = tmp_path
    session.behavior = Behavior.off()
    session._behavior_runtime = session.behavior.runtime()
    session.capture = "screenshot"
    session.driver = MagicMock()
    session.get_page.return_value = MagicMock()
    session.take_screenshot.return_value = tmp_path / "screenshot.png"
    session.element_exists.return_value = True
    locator = MagicMock()
    locator.count.return_value = 1
    session.find.return_value = locator
    session.parse_elements.return_value = [{"title": "hello"}]
    session.dom.return_value = "<p>hello</p>"
    return session
