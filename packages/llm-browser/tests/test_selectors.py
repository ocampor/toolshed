"""Tests for selector resolution."""

from unittest.mock import MagicMock

import pytest

from llm_browser.selectors import (
    CssSelector,
    FallbackSelector,
    IdSelector,
    ScopedSelector,
    XpathSelector,
    describe_selector,
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


def test_fallback_probe_never_waits_inside_the_driver(
    driver: MagicMock, page: MagicMock
) -> None:
    """Resolution asks "does the primary match right now"; `count` may retry
    internally, which would stall every tick of an explicit wait."""
    selector = FallbackSelector(
        primary=CssSelector(css="#a"), fallback=CssSelector(css="#b")
    )
    page.locator.return_value.count.return_value = 0

    resolve_selector(driver, page, selector)

    driver.count.assert_called_once()


# --- scoped selectors (`in:`) ---


def test_a_scoped_selector_looks_inside_the_nth_match(
    driver: MagicMock, page: MagicMock
) -> None:
    page.locator.return_value.count.return_value = 3
    driver.nth.side_effect = lambda loc, index: f"row-{index}"
    driver.child.side_effect = lambda element, sel: f"{element} {sel}"

    found = resolve_selector(
        driver, page, ScopedSelector(root="tr.athing", index=1, inner=".title a")
    )

    page.locator.assert_called_once_with("tr.athing")
    assert found == "row-1 .title a"


def test_a_scoped_selector_says_so_when_the_row_is_gone(
    driver: MagicMock, page: MagicMock
) -> None:
    """A page that dropped rows mid-loop fails the pass with what happened."""
    page.locator.return_value.count.return_value = 1

    with pytest.raises(
        ValueError, match="matches 1 elements now, so element 2 is gone"
    ):
        resolve_selector(
            driver, page, ScopedSelector(root="tr.athing", index=2, inner="a")
        )


def test_a_fallback_cannot_be_scoped(driver: MagicMock, page: MagicMock) -> None:
    inner = FallbackSelector(
        primary=CssSelector(css="#a"), fallback=CssSelector(css="#b")
    )
    scoped = ScopedSelector(root="tr", index=0, inner=inner)

    with pytest.raises(ValueError, match="fallback selector cannot be scoped"):
        resolve_selector(driver, page, scoped)


def test_a_scoped_selector_describes_itself() -> None:
    scoped = ScopedSelector(
        root="tr.athing", index=2, inner=XpathSelector(xpath="./td")
    )
    assert describe_selector(scoped) == "tr.athing[2] xpath=./td"
