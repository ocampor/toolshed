"""Driver-agnostic explicit waits: a Python poll loop, not a driver wait.

Shaped like Selenium's ``WebDriverWait.until`` — ask the cheapest driver
primitive whether the state is reached, sleep a jittered interval, repeat
until the deadline. Deliberately *not* built on a driver-native wait: on the
Playwright family that runs an injected in-page script, which is the
fingerprint an explicit wait is meant to avoid. Every primitive it calls
answers immediately — ``count``, ``is_visible`` and ``text_content`` are
single reads — because a tick that waited inside the driver would blow past
this loop's deadline.
"""

import time
from typing import Any, Callable

from llm_browser.behavior import Jitter
from llm_browser.constants import (
    DEFAULT_SETTLE_MS,
    DESTROYED_CONTEXT_MESSAGE,
    POLL_JITTER_RATIO,
    READ_TIMEOUT_MS,
)
from llm_browser.drivers.base import Driver
from llm_browser.models import WaitState, check_text_state
from llm_browser.scripts import text_match_js
from llm_browser.selectors import Selector, describe_selector, resolve_selector

StatePredicate = Callable[[Driver, Any], bool]


def is_attached(driver: Driver, locator: Any) -> bool:
    return driver.count(locator) > 0


def is_detached(driver: Driver, locator: Any) -> bool:
    try:
        return driver.count(locator) == 0
    except Exception as exc:
        # The navigation that tore the context down is the very thing this
        # wait is watching for; answer "not yet" and re-ask next tick.
        if DESTROYED_CONTEXT_MESSAGE not in str(exc):
            raise
        return False


def is_visible(driver: Driver, locator: Any) -> bool:
    """A locator matching nothing is not visible, so this covers absence too."""
    return driver.is_visible(driver.first(locator))


def is_hidden(driver: Driver, locator: Any) -> bool:
    return not is_visible(driver, locator)


def is_enabled(driver: Driver, locator: Any) -> bool:
    """An element not there yet is neither enabled nor disabled, and asking a driver about it raises."""
    return is_attached(driver, locator) and driver.is_enabled(driver.first(locator))


def is_disabled(driver: Driver, locator: Any) -> bool:
    return is_attached(driver, locator) and not driver.is_enabled(driver.first(locator))


STATE_PREDICATES: dict[WaitState, StatePredicate] = {
    "attached": is_attached,
    "detached": is_detached,
    "visible": is_visible,
    "hidden": is_hidden,
    "enabled": is_enabled,
    "disabled": is_disabled,
}


class TextSettled:
    """The one state with memory, so each wait gets its own instance; a missing element counts as a change."""

    def __init__(self, settle_ms: int) -> None:
        self.settle_s = settle_ms / 1000.0
        self.text: str | None = None
        self.since = time.monotonic()

    def __call__(self, driver: Driver, locator: Any) -> bool:
        text = driver.text_content(driver.first(locator))
        now = time.monotonic()
        if text is None or text != self.text:
            self.text, self.since = text, now
            return False
        return now - self.since >= self.settle_s


def state_predicate(state: WaitState, settle_ms: int) -> StatePredicate:
    if state == "stable":
        return TextSettled(settle_ms)
    return STATE_PREDICATES[state]


def poll_jitter(interval_ms: int) -> Jitter:
    spread = round(interval_ms * POLL_JITTER_RATIO)
    return Jitter(min_ms=max(0, interval_ms - spread), max_ms=interval_ms + spread)


def poll_for_state(
    driver: Driver,
    page: Any,
    selector: Selector,
    state: WaitState,
    timeout_ms: int,
    interval_ms: int,
    settle_ms: int = DEFAULT_SETTLE_MS,
) -> None:
    """``timeout_ms`` is a budget: the sleep is clamped, and ``0`` is exactly one check.
    The locator is re-resolved each tick, since a driver locator can cache a node the page swapped out.
    """
    reached = state_predicate(state, settle_ms)
    poll_until(
        lambda: reached(driver, resolve_selector(driver, page, selector)),
        f"{describe_selector(selector)} did not become {state}",
        timeout_ms,
        interval_ms,
    )


def poll_until(
    reached: Callable[[], bool],
    description: str,
    timeout_ms: int,
    interval_ms: int,
) -> None:
    """``description`` is the timeout message up to ``within <timeout>ms``."""
    pause = poll_jitter(interval_ms)
    deadline = time.monotonic() + timeout_ms / 1000.0
    while True:
        if reached():
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"{description} within {timeout_ms}ms")
        time.sleep(min(pause.sample_seconds(), remaining))


def text_present(
    driver: Driver,
    page: Any,
    text: str,
    *,
    selector: Selector | None = None,
    exact: bool = False,
) -> bool:
    """Normalised ``innerText``; a scope means every match, and a scope matching nothing answers ``False``."""
    script = text_match_js(text, exact)
    if selector is None:
        return bool(driver.evaluate(page, script))
    elements = driver.all(resolve_selector(driver, page, selector))
    return any(matches_now(driver, element, script) for element in elements)


def matches_now(driver: Driver, element: Any, script: str) -> bool:
    """Bounded so a scope cannot become a driver-side wait; a detached scope has no text this tick."""
    try:
        return bool(driver.evaluate(element, script, READ_TIMEOUT_MS))
    except Exception as exc:
        # patchright's TimeoutError is not playwright's, and neither is the builtin.
        if type(exc).__name__ == "TimeoutError":
            return False
        raise


def poll_for_text(
    driver: Driver,
    page: Any,
    text: str,
    *,
    selector: Selector | None = None,
    exact: bool = False,
    state: WaitState = "attached",
    timeout_ms: int,
    interval_ms: int,
) -> None:
    wanted = check_text_state(state)
    scope = f" inside {describe_selector(selector)}" if selector is not None else ""
    poll_until(
        lambda: (
            text_present(driver, page, text, selector=selector, exact=exact) is wanted
        ),
        f"text {text!r}{scope} did not become {'present' if wanted else 'absent'}",
        timeout_ms,
        interval_ms,
    )
