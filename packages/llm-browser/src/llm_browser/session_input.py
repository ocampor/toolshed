"""The input half of ``BrowserSession``: resolve, pace, drive the element.

Every one of these owns the same three decisions so no caller has to: wait for
the element, bracket the interaction in ``paced`` and pick the humanized or the
plain driver primitive from ``Behavior``. ``BrowserSession`` exposes each as a
one-line method; actions and the CLI call those and never reach for the driver.
"""

from typing import TYPE_CHECKING, Any

from llm_browser.behavior import jittered_sleep, paced
from llm_browser.constants import DEFAULT_FIND_TIMEOUT_MS
from llm_browser.selectors import Selector

if TYPE_CHECKING:
    from llm_browser.session import BrowserSession


def click(
    session: "BrowserSession",
    selector: Selector,
    *,
    dispatch: bool = False,
    timeout: int = DEFAULT_FIND_TIMEOUT_MS,
) -> None:
    """``dispatch=True`` fires an untrusted DOM event — driver rule 2's opt-out,
    for overlays that real input cannot reach."""
    with paced(session.behavior, session.behavior_runtime):
        click_element(
            session, session.find(selector, timeout=timeout), dispatch=dispatch
        )


def click_element(
    session: "BrowserSession", element: Any, *, dispatch: bool = False
) -> None:
    """Click an element the caller already resolved.

    The one place the humanized-vs-plain-vs-dispatch choice is made, so a
    session method that found its element some other way — ``pick`` walking a
    list, ``download_file`` arming a download — clicks like every other click.
    Pacing belongs to whoever opened the action, not here.
    """
    if dispatch:
        session.driver.dispatch_event(element, "click")
    elif session.behavior.mouse_move:
        session.driver.humanized_click(
            session.get_page(), element, session.behavior, session.behavior_runtime
        )
    else:
        session.driver.click(element)


def fill(
    session: "BrowserSession",
    selector: Selector,
    value: str,
    *,
    timeout: int = DEFAULT_FIND_TIMEOUT_MS,
) -> None:
    with paced(session.behavior, session.behavior_runtime):
        element = session.find(selector, timeout=timeout)
        if session.behavior.fill_as_type:
            type_humanized(session, element, value)
        else:
            session.driver.fill(element, value)


def type(  # shadows the builtin to mirror the `type` action's name
    session: "BrowserSession",
    selector: Selector,
    value: str,
    *,
    delay_ms: int = 0,
    timeout: int = DEFAULT_FIND_TIMEOUT_MS,
) -> None:
    """An explicit ``delay_ms`` is the caller's own cadence, so it wins over the
    behaviour's per-key jitter."""
    with paced(session.behavior, session.behavior_runtime):
        element = session.find(selector, timeout=timeout)
        if delay_ms > 0 or session.behavior.type_char_delay.max_ms == 0:
            session.driver.type(element, value, delay_ms=delay_ms)
        else:
            type_humanized(session, element, value)


def press(
    session: "BrowserSession",
    selector: Selector | None,
    key: str,
    *,
    timeout: int = DEFAULT_FIND_TIMEOUT_MS,
) -> None:
    """``selector=None`` presses whatever holds focus."""
    with paced(session.behavior, session.behavior_runtime):
        if session.behavior.mouse_move:
            jittered_sleep(
                session.behavior.pre_click_pause, session.behavior_runtime.rng
            )
        if selector is None:
            session.driver.press_focused(session.get_page(), key)
            return
        session.driver.press(session.find(selector, timeout=timeout), key)


def select_option(
    session: "BrowserSession",
    selector: Selector,
    value: str,
    *,
    timeout: int = DEFAULT_FIND_TIMEOUT_MS,
) -> None:
    with paced(session.behavior, session.behavior_runtime):
        session.driver.select_option(session.find(selector, timeout=timeout), value)


def set_checked(
    session: "BrowserSession",
    selector: Selector,
    checked: bool,
    *,
    timeout: int = DEFAULT_FIND_TIMEOUT_MS,
) -> None:
    with paced(session.behavior, session.behavior_runtime):
        session.driver.set_checked(session.find(selector, timeout=timeout), checked)


def type_humanized(session: "BrowserSession", element: Any, value: str) -> None:
    session.driver.humanized_type(
        session.get_page(), element, value, session.behavior, session.behavior_runtime
    )
