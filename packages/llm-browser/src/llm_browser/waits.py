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

import random
import time
from typing import Any, Callable

from llm_browser.behavior import Jitter
from llm_browser.constants import (
    DEFAULT_SETTLE_MS,
    DESTROYED_CONTEXT_MESSAGE,
    POLL_JITTER_RATIO,
)
from llm_browser.drivers.base import Driver
from llm_browser.models import WaitState
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


STATE_PREDICATES: dict[WaitState, StatePredicate] = {
    "attached": is_attached,
    "detached": is_detached,
    "visible": is_visible,
    "hidden": is_hidden,
}


class TextSettled:
    """True once the element's text has held still for ``settle_ms``.

    The one state with memory, so each wait gets its own instance. An element
    that is not there yet reads as ``None`` and counts as a change: nothing
    has settled while there is nothing to read.
    """

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
    rng: random.Random,
    settle_ms: int = DEFAULT_SETTLE_MS,
) -> None:
    """Block until ``selector`` reaches ``state``, or raise ``TimeoutError``.

    ``timeout_ms`` is a budget, not a floor: the sleep is clamped to what is
    left of it, so the wait costs at most one more state check past the
    deadline and ``timeout_ms=0`` is exactly one check.

    The locator is re-resolved every tick: a driver locator can cache the
    element it matched, and a node the page swapped out would then never be
    seen to change state. With a ``FallbackSelector`` that re-resolution can
    switch branches mid-wait, so ``detached`` is judged against whichever
    branch matched this tick — it never fires while the fallback still
    matches.
    """
    reached = state_predicate(state, settle_ms)
    pause = poll_jitter(interval_ms)
    deadline = time.monotonic() + timeout_ms / 1000.0
    while True:
        if reached(driver, resolve_selector(driver, page, selector)):
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"{describe_selector(selector)} did not become "
                f"{state} within {timeout_ms}ms"
            )
        time.sleep(min(pause.sample_seconds(rng), remaining))
