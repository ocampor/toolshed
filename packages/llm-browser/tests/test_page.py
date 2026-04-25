"""Tests for BrowserSession interaction methods."""

from unittest.mock import MagicMock

import pytest

from llm_browser.session import BrowserSession


def _single_locator() -> MagicMock:
    """Create a locator mock that reports exactly one element."""
    locator = MagicMock()
    locator.count.return_value = 1
    return locator


@pytest.fixture
def session(tmp_path: object) -> BrowserSession:
    """Create a BrowserSession with a mock page injected."""
    s = BrowserSession(state_dir=tmp_path)  # type: ignore[arg-type]
    mock_page = MagicMock()
    mock_page.locator.return_value = _single_locator()
    s._page = mock_page
    return s


@pytest.fixture
def page(session: BrowserSession) -> MagicMock:
    return session._page  # type: ignore[return-value]


# --- Properties ---


# --- goto ---


def test_goto(session: BrowserSession, page: MagicMock) -> None:
    session.goto("https://example.com")
    page.goto.assert_called_once_with(
        "https://example.com", wait_until="domcontentloaded"
    )


def test_goto_custom_wait_until(session: BrowserSession, page: MagicMock) -> None:
    session.goto("https://example.com", wait_until="networkidle")
    page.goto.assert_called_once_with("https://example.com", wait_until="networkidle")


# --- find / find_all / element_exists ---


def test_find(session: BrowserSession, page: MagicMock) -> None:
    locator = page.locator.return_value
    result = session.find("#btn")
    locator.first.wait_for.assert_called_once_with(state="visible", timeout=10_000)
    assert result is locator.first


def test_find_raises_on_multiple(session: BrowserSession, page: MagicMock) -> None:
    locator = _single_locator()
    locator.count.return_value = 3
    page.locator.return_value = locator
    with pytest.raises(ValueError, match="Expected 1 element"):
        session.find("#btn")


def test_find_all(session: BrowserSession, page: MagicMock) -> None:
    locator = page.locator.return_value
    result = session.find_all("li.item")
    locator.first.wait_for.assert_called_once_with(state="attached", timeout=10_000)
    assert result is locator


def test_element_exists_true(session: BrowserSession) -> None:
    assert session.element_exists("#exists") is True


def test_element_exists_false(session: BrowserSession, page: MagicMock) -> None:
    locator = _single_locator()
    locator.first.wait_for.side_effect = TimeoutError
    page.locator.return_value = locator
    assert session.element_exists("#missing") is False


# --- pick ---


def test_pick(session: BrowserSession, page: MagicMock) -> None:
    locator = MagicMock()
    locator.count.return_value = 2
    item1 = MagicMock()
    item1.text_content.return_value = "Apple"
    item2 = MagicMock()
    item2.text_content.return_value = "Banana"
    locator.nth.side_effect = lambda i: [item1, item2][i]
    locator.first.wait_for.return_value = None
    page.locator.return_value = locator
    session.pick(".option", "Banana")
    item2.click.assert_called_once()


def test_pick_single_clicks_first(session: BrowserSession, page: MagicMock) -> None:
    locator = MagicMock()
    locator.count.return_value = 1
    locator.first.wait_for.return_value = None
    page.locator.return_value = locator
    session.pick(".option", "anything")
    locator.first.click.assert_called_once()


def test_pick_no_match_raises(session: BrowserSession, page: MagicMock) -> None:
    locator = MagicMock()
    locator.count.return_value = 2
    item = MagicMock()
    item.text_content.return_value = "Other"
    locator.nth.return_value = item
    locator.first.wait_for.return_value = None
    page.locator.return_value = locator
    with pytest.raises(ValueError, match="No element with text"):
        session.pick(".option", "Missing")


# --- wait_for_load_state ---


def test_wait_for_load_state(session: BrowserSession, page: MagicMock) -> None:
    session.wait_for_load_state("load", timeout=5000)
    page.wait_for_load_state.assert_called_once_with("load", timeout=5000)


# --- frame ---


def test_frame_returns_frame(session: BrowserSession, page: MagicMock) -> None:
    locator = page.locator.return_value
    frame_mock = MagicMock()
    locator.first.element_handle.return_value.content_frame.return_value = frame_mock
    result = session.frame("iframe#main")
    assert result is frame_mock


# --- parse_elements ---


def test_parse_elements(session: BrowserSession, page: MagicMock) -> None:
    row1 = MagicMock()
    child1 = MagicMock()
    child1.text_content.return_value = "Alice"
    row1.locator.return_value = child1

    row2 = MagicMock()
    child2 = MagicMock()
    child2.text_content.return_value = "Bob"
    row2.locator.return_value = child2

    locator = MagicMock()
    locator.all.return_value = [row1, row2]
    page.locator.return_value = locator

    from llm_browser.models import ExtractField

    result = session.parse_elements(
        "tr.row",
        {"name": ExtractField(child_selector="td.name", attribute="textContent")},
    )
    assert result == [{"name": "Alice"}, {"name": "Bob"}]


# --- dom ---


def test_dom(session: BrowserSession, page: MagicMock) -> None:
    locator = page.locator.return_value
    locator.first.evaluate.return_value = "<div><p>Hello</p></div>"
    result = session.dom("#content")
    assert "Hello" in result
    locator.first.evaluate.assert_called_once_with("el => el.outerHTML")


# --- Typed selectors ---


def test_find_with_id_selector(session: BrowserSession, page: MagicMock) -> None:
    from llm_browser.selectors import IdSelector

    session.find(IdSelector(id="my-field"))
    page.locator.assert_called_with('[id="my-field"]')


def test_find_with_xpath_selector(session: BrowserSession, page: MagicMock) -> None:
    from llm_browser.selectors import XpathSelector

    session.find(XpathSelector(xpath="//input[@name='q']"))
    page.locator.assert_called_with("xpath=//input[@name='q']")
