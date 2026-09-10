"""The session's input methods: resolve, pace, pick the driver primitive."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from llm_browser import behavior as behavior_module
from llm_browser.actions import execute_action
from llm_browser.behavior import Behavior, Jitter
from llm_browser.models import ClickStep
from llm_browser.session import BrowserSession

PACE_MS = 40
PACED = Behavior(
    post_action_pause=Jitter(min_ms=PACE_MS, max_ms=PACE_MS),
    mouse_move=False,
    fill_as_type=False,
    type_char_delay=Jitter(),
    pre_click_pause=Jitter(),
)


@pytest.fixture
def session(tmp_path: Path) -> BrowserSession:
    s = BrowserSession(state_dir=tmp_path)
    s._page = MagicMock()
    s.driver = MagicMock()
    s.driver.count.return_value = 1
    s.driver.is_visible.return_value = True
    s.driver.first.return_value = "element"
    return s


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr(behavior_module.time, "sleep", recorded.append)
    return recorded


def driver(session: BrowserSession) -> Any:
    return session.driver


# --- routing to driver primitives ---


def test_click_uses_the_plain_primitive(session: BrowserSession) -> None:
    session.click("#btn")
    driver(session).click.assert_called_once_with("element")
    driver(session).dispatch_event.assert_not_called()


def test_click_dispatch_is_opt_in(session: BrowserSession) -> None:
    session.click("#btn", dispatch=True)
    driver(session).dispatch_event.assert_called_once_with("element", "click")
    driver(session).click.assert_not_called()


def test_click_humanizes_when_the_behavior_moves_the_mouse(
    session: BrowserSession,
) -> None:
    session.behavior = Behavior.human()
    session.behavior_runtime = session.behavior.runtime()
    session.click("#btn")
    driver(session).humanized_click.assert_called_once()
    driver(session).click.assert_not_called()


def test_fill_uses_the_plain_primitive_when_fill_as_type_is_off(
    session: BrowserSession,
) -> None:
    session.fill("#input", "hello")
    driver(session).fill.assert_called_once_with("element", "hello")


def test_fill_types_when_fill_as_type_is_on(session: BrowserSession) -> None:
    session.behavior = Behavior.pace()
    session.behavior_runtime = session.behavior.runtime()
    session.fill("#input", "hello")
    driver(session).humanized_type.assert_called_once()
    driver(session).fill.assert_not_called()


def test_type_with_an_explicit_delay_beats_the_behavior(
    session: BrowserSession,
) -> None:
    session.behavior = Behavior.human()
    session.behavior_runtime = session.behavior.runtime()
    session.type("#search", "query", delay_ms=50)
    driver(session).type.assert_called_once_with("element", "query", delay_ms=50)
    driver(session).humanized_type.assert_not_called()


def test_type_humanizes_when_the_behavior_has_a_key_delay(
    session: BrowserSession,
) -> None:
    session.behavior = Behavior.human()
    session.behavior_runtime = session.behavior.runtime()
    session.type("#search", "query")
    driver(session).humanized_type.assert_called_once()


def test_press_without_a_selector_goes_to_the_focused_element(
    session: BrowserSession,
) -> None:
    session.press(None, "Enter")
    driver(session).press_focused.assert_called_once_with(session._page, "Enter")
    driver(session).press.assert_not_called()
    driver(session).resolve.assert_not_called()


def test_press_with_a_selector_resolves_it(session: BrowserSession) -> None:
    session.press("#field", "Enter")
    driver(session).press.assert_called_once_with("element", "Enter")
    driver(session).press_focused.assert_not_called()


def test_select_option(session: BrowserSession) -> None:
    session.select_option("#dropdown", "opt2")
    driver(session).select_option.assert_called_once_with("element", "opt2")


def test_set_checked(session: BrowserSession) -> None:
    session.set_checked("#cb", False)
    driver(session).set_checked.assert_called_once_with("element", False)


# --- pacing ---


def test_input_marks_the_action_done(session: BrowserSession) -> None:
    assert session.behavior_runtime.last_action_monotonic is None
    session.click("#btn")
    assert session.behavior_runtime.last_action_monotonic is not None


def test_input_pauses_after_the_action(
    session: BrowserSession, sleeps: list[float]
) -> None:
    session.behavior = PACED
    session.behavior_runtime = session.behavior.runtime()
    session.click("#btn")
    assert sleeps == [PACE_MS / 1000.0]


def test_a_failed_input_skips_the_post_pause(
    session: BrowserSession, sleeps: list[float]
) -> None:
    session.behavior = PACED
    session.behavior_runtime = session.behavior.runtime()
    session.driver.click.side_effect = TimeoutError("gone")
    with pytest.raises(TimeoutError):
        session.click("#btn")
    assert sleeps == []


def test_an_action_paces_once_not_twice(
    session: BrowserSession, sleeps: list[float]
) -> None:
    """``execute_action`` opens the pacing scope; the session method it calls
    must defer to it rather than pause a second time."""
    session.behavior = PACED
    session.behavior_runtime = session.behavior.runtime()
    execute_action(session, ClickStep(name="s", action="click", selector="#btn"))
    assert sleeps == [PACE_MS / 1000.0]
