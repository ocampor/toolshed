"""nodriver runs a page script the way the Playwright family reads it.

The library writes its scripts as function literals (``el => el.outerHTML``,
``page_probe.js``). CDP does neither half by itself, and both wrong answers
are a silent ``None`` rather than an error — so this pins which string gets
invoked and which gets evaluated.
"""

import asyncio
import re
from pathlib import Path
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
        ("missing", "no <option> matching 'z' by value or label in the select"),
        ("option-disabled", "the <option> matching 'z' is disabled"),
        ("group-disabled", "the <optgroup> holding 'z' is disabled"),
        ("select-disabled", "the <select> is disabled, so 'z' cannot be chosen"),
        ("not-a-select", "select_option needs a <select>"),
        ("something-else", "could not select the <option> matching 'z'"),
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


def test_the_visibility_read_asks_the_platform_first() -> None:
    """A box read cannot see `visibility: hidden` -- the element still has a
    box -- and `opacity: 0` has to stay visible, so only the CSS check is on."""
    from llm_browser.drivers.nodriver import VISIBILITY_SCRIPT

    assert "checkVisibility({checkVisibilityCSS: true})" in VISIBILITY_SCRIPT
    assert "opacityProperty" not in VISIBILITY_SCRIPT
    assert "getClientRects" in VISIBILITY_SCRIPT


# --- keyboard ---


@pytest.mark.parametrize(
    ("key", "triplet"),
    [
        ("Enter", ("Enter", "Enter", 13)),
        ("a", ("a", "KeyA", 65)),
        ("Z", ("Z", "KeyZ", 90)),
        ("7", ("7", "Digit7", 55)),
        ("+", ("+", "", 0)),
    ],
)
def test_a_key_carries_its_virtual_key_code(
    key: str, triplet: tuple[str, str, int]
) -> None:
    from llm_browser.drivers.nodriver import key_triplet

    assert key_triplet(key) == triplet


@pytest.mark.parametrize(
    ("chord", "expected"),
    [
        ("Control+a", (["Control"], "a")),
        ("Shift+Tab", (["Shift"], "Tab")),
        ("Control+Shift+k", (["Control", "Shift"], "k")),
        ("Enter", ([], "Enter")),
        ("+", ([], "+")),
    ],
)
def test_a_chord_splits_into_modifiers_and_a_key(
    chord: str, expected: tuple[list[str], str]
) -> None:
    from llm_browser.drivers.nodriver import split_chord

    assert split_chord(chord) == expected


def test_an_unknown_modifier_is_a_value_error() -> None:
    from llm_browser.drivers.nodriver import split_chord

    with pytest.raises(ValueError, match="unknown key modifier 'Hyper'"):
        split_chord("Hyper+a")


class KeyboardTab:
    """Records the `Input.dispatchKeyEvent` arguments, not the CDP wrapper."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def send(self, command: Any) -> None:
        self.events.append(command)


@pytest.fixture
def recorded_keys(monkeypatch: pytest.MonkeyPatch) -> KeyboardTab:
    tab = KeyboardTab()

    def fake_module(*names: str) -> Any:
        module = MagicMock()
        module.cdp.input_.dispatch_key_event = lambda event_type, **kwargs: {
            "type": event_type,
            **kwargs,
        }
        module.cdp.dom.focus = lambda **kwargs: {"type": "focus"}
        return module

    monkeypatch.setattr(nodriver_driver, "load_optional_module", fake_module)
    return tab


def test_a_typed_character_fires_a_keydown_with_its_text(
    recorded_keys: KeyboardTab,
) -> None:
    """`char` alone — what nodriver's `send_keys` sends — fires no keydown."""
    asyncio.new_event_loop().run_until_complete(
        nodriver_driver.press_key(recorded_keys, "a")
    )
    assert [e["type"] for e in recorded_keys.events] == ["keyDown", "keyUp"]
    assert recorded_keys.events[0]["text"] == "a"
    assert recorded_keys.events[0]["windows_virtual_key_code"] == 65


def test_a_chord_holds_its_modifier_down_and_types_nothing(
    recorded_keys: KeyboardTab,
) -> None:
    asyncio.new_event_loop().run_until_complete(
        nodriver_driver.press_chord(recorded_keys, "Control+a")
    )
    assert [(e["type"], e["key"], e["modifiers"]) for e in recorded_keys.events] == [
        ("rawKeyDown", "Control", 2),
        ("rawKeyDown", "a", 2),
        ("keyUp", "a", 2),
        ("keyUp", "Control", 0),
    ]
    assert all("text" not in e for e in recorded_keys.events)


# --- the tab stays in the foreground ---


class ForegroundTab:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def activate(self) -> None:
        self.calls.append("activate")

    async def get(self, url: str) -> None:
        self.calls.append(f"get {url}")

    async def save_screenshot(self, **kwargs: Any) -> str:
        self.calls.append(f"save_screenshot {kwargs['format']}")
        Path(kwargs["filename"]).write_bytes(b"png")
        return kwargs["filename"]


def test_goto_activates_the_tab_it_is_about_to_drive() -> None:
    """Chromium throttles a background tab's timers and stalls a capture on
    it; one `window.open` is enough to leave the opener there for good."""
    tab = ForegroundTab()
    driver_with_loop().goto(tab, "http://example.test", "load")
    assert tab.calls == ["activate", "get http://example.test"]


def test_a_screenshot_activates_the_tab_first() -> None:
    tab = ForegroundTab()
    driver_with_loop().screenshot_bytes(tab)
    assert tab.calls == ["activate", "save_screenshot png"]


# --- a write path never dereferences a miss ---


class EmptyScope:
    """A parent whose child selector matches nothing."""

    async def query_selector_all(self, selector: str) -> list[Any]:
        return []


@pytest.mark.parametrize(
    ("drive", "args"),
    [
        (NodriverDriver.click, ()),
        (NodriverDriver.press, ("Enter",)),
        (NodriverDriver.type, ("hello",)),
        (NodriverDriver.set_checked, (True,)),
    ],
)
def test_a_write_to_a_missing_element_is_a_value_error(
    drive: Any, args: tuple[Any, ...], stub_cdp: None
) -> None:
    """`AttributeError` on `None` would escape `run_flow` as a raw traceback;
    a `ValueError` is what `execute_action` turns into an `ErrorResult`."""
    locator = NodriverLocator(tab=None, selector="td.gone", parent=EmptyScope())
    with pytest.raises(ValueError, match="no element matched 'td.gone'"):
        drive(driver_with_loop(), locator, *args)


def test_a_read_of_a_missing_element_is_still_a_miss() -> None:
    """Rule 1: the read paths answer a miss, they do not raise."""
    locator = NodriverLocator(tab=None, selector="td.gone", parent=EmptyScope())
    driver = driver_with_loop()
    assert driver.get_attribute(locator, "href") is None
    assert driver.input_value(locator) == ""


def test_a_script_behind_a_comment_is_still_a_function() -> None:
    """Not detecting it costs a silent `undefined`, not an error."""
    assert is_function_literal("// what this reads\nel => el.value")
    assert not is_function_literal("// a note\ndocument.readyState")
