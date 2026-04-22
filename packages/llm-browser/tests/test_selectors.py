"""Tests for selector resolution."""

from unittest.mock import MagicMock

import pytest

from llm_browser.selectors import (
    CssSelector,
    FallbackSelector,
    IdSelector,
    XpathSelector,
    parse_selector,
    resolve_selector,
)


@pytest.fixture
def page() -> MagicMock:
    mock = MagicMock()
    mock.locator.return_value = MagicMock()
    return mock


@pytest.fixture
def driver(page: MagicMock) -> MagicMock:
    mock = MagicMock()
    mock.resolve.side_effect = lambda p, sel: p.locator(sel)
    mock.count.side_effect = lambda loc: loc.count()
    return mock


# --- resolve_selector with typed models ---


def test_resolve_string_selector(driver: MagicMock, page: MagicMock) -> None:
    resolve_selector(driver, page, "#btn")
    page.locator.assert_called_once_with("#btn")


def test_resolve_css_model(driver: MagicMock, page: MagicMock) -> None:
    resolve_selector(driver, page, CssSelector(css=".my-class"))
    page.locator.assert_called_once_with(".my-class")


def test_resolve_xpath_model(driver: MagicMock, page: MagicMock) -> None:
    resolve_selector(driver, page, XpathSelector(xpath="//button[@id='x']"))
    page.locator.assert_called_once_with("xpath=//button[@id='x']")


def test_resolve_id_model(driver: MagicMock, page: MagicMock) -> None:
    resolve_selector(driver, page, IdSelector(id="135textbox78"))
    page.locator.assert_called_once_with('[id="135textbox78"]')


def test_resolve_fallback_uses_primary(driver: MagicMock, page: MagicMock) -> None:
    primary_locator = MagicMock()
    primary_locator.count.return_value = 1
    fallback_locator = MagicMock()

    def locator_side_effect(sel: str) -> MagicMock:
        if sel == "#primary":
            return primary_locator
        return fallback_locator

    page.locator.side_effect = locator_side_effect

    selector = FallbackSelector(
        primary=CssSelector(css="#primary"),
        fallback=CssSelector(css="#fallback"),
    )
    result = resolve_selector(driver, page, selector)
    assert result is primary_locator


def test_resolve_fallback_uses_fallback(driver: MagicMock, page: MagicMock) -> None:
    primary_locator = MagicMock()
    primary_locator.count.return_value = 0
    fallback_locator = MagicMock()

    def locator_side_effect(sel: str) -> MagicMock:
        if sel == "#primary":
            return primary_locator
        return fallback_locator

    page.locator.side_effect = locator_side_effect

    selector = FallbackSelector(
        primary=CssSelector(css="#primary"),
        fallback=CssSelector(css="#fallback"),
    )
    result = resolve_selector(driver, page, selector)
    assert result is fallback_locator


# --- parse_selector ---


def test_parse_string() -> None:
    assert parse_selector("#btn") == "#btn"


def test_parse_css_dict() -> None:
    result = parse_selector({"css": ".my-class"})
    assert result == CssSelector(css=".my-class")


def test_parse_xpath_dict() -> None:
    result = parse_selector({"xpath": "//button"})
    assert result == XpathSelector(xpath="//button")


def test_parse_id_dict() -> None:
    result = parse_selector({"id": "myfield"})
    assert result == IdSelector(id="myfield")


def test_parse_fallback_dict() -> None:
    result = parse_selector({"primary": {"css": "#a"}, "fallback": {"id": "b"}})
    assert result == FallbackSelector(
        primary=CssSelector(css="#a"), fallback=IdSelector(id="b")
    )


def test_parse_already_model() -> None:
    model = CssSelector(css="#x")
    assert parse_selector(model) is model  # type: ignore[arg-type]


def test_parse_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown selector format"):
        parse_selector({"unknown": "value"})
