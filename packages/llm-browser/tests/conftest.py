from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from llm_browser.behavior import Behavior
from llm_browser.drivers.base import Driver
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
    session.screenshot_bytes.return_value = PNG
    session.dom_snapshot.return_value = "<html><body>hi</body></html>"
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


ExploringSession = Callable[..., BrowserSession]


@pytest.fixture
def exploring_session(tmp_path: Path) -> ExploringSession:
    """Build a session whose driver answers ``explore`` from canned rows.

    Each row maps a child selector (``None`` for the row element itself) to
    what reading it returns, so a test states the page as the extract sees it.
    """

    def build(
        rows: list[dict[str | None, str | None]], text: str = ""
    ) -> BrowserSession:
        driver = MagicMock(spec=Driver)
        driver.count.return_value = len(rows)
        driver.nth.side_effect = lambda locator, index: index
        driver.read_field.side_effect = lambda index, field: rows[index].get(
            field["child_selector"]
        )
        driver.read_property.return_value = text
        session = BrowserSession(state_dir=tmp_path)
        session.driver = driver
        session._page = MagicMock()
        return session

    return build
