"""nodriver runs a page script the way the Playwright family reads it.

The library writes its scripts as function literals (``el => el.outerHTML``,
``page_probe.js``). CDP does neither half by itself, and both wrong answers
are a silent ``None`` rather than an error — so this pins which string gets
invoked and which gets evaluated.
"""

import asyncio
import re
from typing import Any
from unittest.mock import MagicMock

import pytest

from llm_browser.drivers import nodriver as nodriver_driver
from llm_browser.drivers.nodriver import (
    NodriverDriver,
    NodriverLocator,
    is_function_literal,
)


@pytest.mark.parametrize(
    "script",
    [
        "el => el.outerHTML",
        "(el) => el.outerHTML",
        "() => { return 1; }",
        "async (el) => el.value",
        "function (el) { return el.value; }",
    ],
)
def test_a_function_literal_is_recognised(script: str) -> None:
    assert is_function_literal(script)


@pytest.mark.parametrize(
    "script",
    [
        "document.readyState",
        "(document.title)",
        "return el.value",
        "window.innerHeight - 10",
    ],
)
def test_an_expression_is_not_a_function_literal(script: str) -> None:
    assert not is_function_literal(script)


class RecordingElement:
    def __init__(self) -> None:
        self.scripts: list[str] = []

    async def apply(self, script: str) -> None:
        self.scripts.append(script)


def driver_with_loop() -> NodriverDriver:
    driver = NodriverDriver()
    driver.loop = asyncio.new_event_loop()
    return driver


def test_an_element_function_literal_is_passed_through() -> None:
    driver = driver_with_loop()
    element = RecordingElement()
    driver.evaluate(NodriverLocator(tab=None, element=element), "el => el.outerHTML")
    assert element.scripts == ["el => el.outerHTML"]


def test_an_element_expression_is_wrapped_as_a_body() -> None:
    driver = driver_with_loop()
    element = RecordingElement()
    driver.evaluate(NodriverLocator(tab=None, element=element), "return el.value")
    assert element.scripts == ["(el) => { return el.value }"]


def test_a_page_function_literal_is_invoked(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def record(tab: Any, expression: str) -> None:
        seen.append(expression)

    monkeypatch.setattr(nodriver_driver, "_evaluate_by_value", record)
    driver_with_loop().evaluate(object(), "() => ({ok: true})")
    assert seen == ["(() => ({ok: true}))()"]


def test_a_page_expression_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def record(tab: Any, expression: str) -> None:
        seen.append(expression)

    monkeypatch.setattr(nodriver_driver, "_evaluate_by_value", record)
    driver_with_loop().evaluate(object(), "document.readyState")
    assert seen == ["document.readyState"]


class ClickableElement:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def scroll_into_view(self) -> None:
        self.calls.append("scroll_into_view")

    async def mouse_click(self) -> None:
        self.calls.append("mouse_click")

    async def click(self) -> None:
        self.calls.append("click")


def test_a_click_scrolls_the_target_into_view_first() -> None:
    """The CDP mouse event carries viewport coordinates, so a target below
    the fold is otherwise clicked where it is not."""
    element = ClickableElement()
    driver_with_loop().click(NodriverLocator(tab=None, element=element))
    assert element.calls == ["scroll_into_view", "mouse_click"]


def test_a_dispatched_click_needs_no_coordinates() -> None:
    element = ClickableElement()
    driver_with_loop().click(NodriverLocator(tab=None, element=element), dispatch=True)
    assert element.calls == ["click"]


class SelectElement:
    """A select whose in-page script has already made up its mind."""

    backend_node_id = 7

    def __init__(self, outcome: str) -> None:
        self.outcome = outcome

    async def apply(self, script: str) -> str:
        return self.outcome


class FocusingTab:
    def __init__(self) -> None:
        self.sent = 0

    async def send(self, command: Any) -> None:
        self.sent += 1


@pytest.fixture
def stub_cdp(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the real `nodriver` package out of `sys.modules`: a sibling test
    asserts the wait paths never pull it in, and an import here is global."""
    monkeypatch.setattr(
        nodriver_driver, "load_optional_module", lambda *names: MagicMock()
    )


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        ("missing", "no <option value='z'> in the select"),
        ("disabled", "<option value='z'> is disabled"),
        ("not-a-select", "select_option needs a <select>"),
        ("something-else", "could not select <option value='z'>"),
    ],
)
def test_a_refused_select_is_a_value_error(
    outcome: str, message: str, stub_cdp: None
) -> None:
    """``ValueError`` is what ``execute_action`` turns into an ``ErrorResult``;
    anything else would abort the flow instead of failing the step."""
    locator = NodriverLocator(tab=FocusingTab(), element=SelectElement(outcome))
    with pytest.raises(ValueError, match=re.escape(message)):
        driver_with_loop().select_option(locator, "z")


def test_a_successful_select_focuses_first(stub_cdp: None) -> None:
    tab = FocusingTab()
    locator = NodriverLocator(tab=tab, element=SelectElement("ok"))
    driver_with_loop().select_option(locator, "c")
    assert tab.sent == 1
