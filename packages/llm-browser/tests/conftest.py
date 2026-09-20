from collections.abc import Callable, Sequence
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from llm_browser.behavior import Behavior
from llm_browser.drivers.base import Driver
from llm_browser.models import PageProbe
from llm_browser.results import BytesResult
from llm_browser.session import BrowserSession
from tests.flow_helpers import stub_matching

PNG = b"\x89PNG\r\n\x1a\nfake"


@pytest.fixture
def mock_session(tmp_path: Path) -> MagicMock:
    session = stub_matching(MagicMock(spec=BrowserSession))
    session.session_dir = tmp_path
    session.behavior = Behavior.off()
    session.capture = "screenshot"
    session.driver = MagicMock()
    session.current_url.return_value = "https://example.test/page"
    session.get_page.return_value = MagicMock()
    session.screenshot_bytes.return_value = PNG
    session.dom_snapshot.return_value = "<html><body>hi</body></html>"
    session.download_file.return_value = BytesResult(
        name="download.bin", content=b"payload"
    )
    session.element_exists.return_value = True
    session.click.return_value = None  # a double hit-tests nothing
    session.probe.return_value = PageProbe()
    locator = MagicMock()
    locator.count.return_value = 1
    session.find.return_value = locator
    session.find_all.return_value = locator
    session.parse_elements.return_value = [{"title": "hello"}]
    session.dom.return_value = "<p>hello</p>"
    return session


ExploringSession = Callable[..., BrowserSession]

# A first match nothing is wrong with; a test states only what it changes.
# `clickable` is not here: the model computes it from `why_not`.
CLICKABLE_FIRST: dict[str, object] = {
    "tag": "a",
    "text": "Alpha",
    "role": None,
    "aria_label": None,
    "name": "Alpha",
    "href": "/alpha",
    "visible": True,
    "enabled": True,
    "in_viewport": True,
    "covered_by": None,
    "hit_tested": True,
    "stable": True,
    "pointer_events": True,
    "why_not": [],
    "nested_controls": [],
}

# What the first match offers a selector when it offers nothing.
NO_LOCATORS: dict[str, object] = {
    "tag": "a",
    "testid_attribute": None,
    "testid": None,
    "testid_depth": 0,
    "aria_label": None,
    "role": None,
    "name": None,
    "id": None,
    "href": None,
    "classes": [],
}


@pytest.fixture
def exploring_session(tmp_path: Path) -> ExploringSession:
    """Build a session whose driver answers ``explore`` from canned rows.

    Each row maps a child selector to what reading it returns, so a test
    states the page as the extract sees it; a selector no key names reads as
    ``None``, and ``text`` is what every row's own element says. ``first``
    overrides the in-page read of the first match, ``candidates`` are what
    that read proposes, and ``matches`` says how many elements a selector
    other than the explored one finds.
    """

    def build(
        rows: list[dict[str | None, str | None]],
        text: str = "",
        first: dict[str, object] | None = None,
        locators: dict[str, object] | None = None,
        matches: dict[str, int] | None = None,
        since_navigation_ms: int = 120,
    ) -> BrowserSession:
        def read(
            target: tuple[int, str | None], name: str, exclude: Sequence[str] = ()
        ) -> str | None:
            index, child_selector = target
            if child_selector is None:
                return rows[index].get(None, text)
            return rows[index].get(child_selector)

        counts = matches or {}
        driver = MagicMock(spec=Driver)
        driver.supports_role_selector = True
        driver.resolve.side_effect = lambda page, selector: selector
        driver.count.side_effect = lambda locator: counts.get(locator, len(rows))
        driver.evaluate.return_value = {
            "first": CLICKABLE_FIRST | (first or {}),
            "locators": NO_LOCATORS | (locators or {}),
            "since_navigation_ms": since_navigation_ms,
        }
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
