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

    Each row maps a child selector to what reading it returns, so a test
    states the page as the extract sees it; a selector no key names reads as
    ``None``, and ``text`` is what every row's own element says.
    """

    def build(
        rows: list[dict[str | None, str | None]], text: str = ""
    ) -> BrowserSession:
        def read(target: tuple[int, str | None], name: str) -> str | None:
            index, child_selector = target
            if child_selector is None:
                return rows[index].get(None, text)
            return rows[index].get(child_selector)

        driver = MagicMock(spec=Driver)
        driver.count.return_value = len(rows)
        driver.nth.side_effect = lambda locator, index: (index, None)
        driver.child.side_effect = lambda element, selector: (element[0], selector)
        driver.read_property.side_effect = read
        driver.get_attribute.side_effect = read
        # The real default, so a canned page exercises the child/read split
        # every driver inherits rather than a mock standing in for it.
        driver.read_field.side_effect = lambda row, field: Driver.read_field(
            driver, row, field
        )
        session = BrowserSession(state_dir=tmp_path)
        session.driver = driver
        session._page = MagicMock()
        return session

    return build
