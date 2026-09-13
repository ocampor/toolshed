"""The input half of ``BrowserSession``: resolve, pace, drive the element.

Every one of these owns the same three decisions so no caller has to: wait for
the element, bracket the interaction in ``paced`` and pick the humanized or the
plain driver primitive from ``Behavior``. ``BrowserSession`` exposes each as a
one-line method; actions and the CLI call those and never reach for the driver.
"""

import logging
from typing import TYPE_CHECKING, Any

from llm_browser.behavior import Behavior, Jitter, jittered_sleep, paced
from llm_browser.constants import DEFAULT_FIND_TIMEOUT_MS, LOGGER_NAME
from llm_browser.results import is_step_failure, is_timeout
from llm_browser.scripts import select_control_tag_js
from llm_browser.selectors import Selector, describe_selector

if TYPE_CHECKING:
    from llm_browser.session import BrowserSession

logger = logging.getLogger(LOGGER_NAME)


# The knobs ``humanize`` switches: every field ``Behavior.human()`` and
# ``Behavior.off()`` disagree on. ``min_gap_ms`` is not one of them — the two
# presets agree on it — so a per-step flag can never hand back a rate limit
# the session set to stay under a site's radar.
HUMANIZE_KNOBS = frozenset(
    name
    for name in Behavior.model_fields
    if getattr(Behavior.human(), name) != getattr(Behavior.off(), name)
)


def driver_opt_out(behavior: Behavior, field: str) -> bool:
    """Whether the session's behaviour class owns this knob itself.

    A driver config that redefines one — camoufox turning ``mouse_move`` off
    because its native C++ Bézier does the moving — keeps it off, or our path
    would run stacked on top of the driver's own.
    """
    declared = behavior.__class__.model_fields[field]
    return bool(declared.default != Behavior.model_fields[field].default)


def switched_on(behavior: Behavior) -> dict[str, Any]:
    """The knobs ``humanize: true`` turns on: those still sitting at their
    ``off()`` value. One the session tuned — a slower key delay, a tighter
    click offset — is already humanized the way its owner meant it to be."""
    human, off = Behavior.human(), Behavior.off()
    return {
        name: getattr(human, name)
        for name in HUMANIZE_KNOBS
        if getattr(behavior, name) == getattr(off, name)
        and not driver_opt_out(behavior, name)
    }


def switched_off() -> dict[str, Any]:
    return {name: getattr(Behavior.off(), name) for name in HUMANIZE_KNOBS}


def behavior_for(session: "BrowserSession", humanize: bool | None) -> Behavior:
    """The behaviour one call runs under. ``humanize`` switches the session's
    humanization knobs on or off for that call — timing included, since a
    humanized action that pauses like an instant one is only half humanized —
    and leaves everything else the session was configured with in place.
    """
    if humanize is None:
        return session.behavior
    knobs = switched_on(session.behavior) if humanize else switched_off()
    return session.behavior.model_copy(update=knobs)


def click(
    session: "BrowserSession",
    selector: Selector,
    *,
    dispatch: bool = False,
    humanize: bool | None = None,
    timeout: int = DEFAULT_FIND_TIMEOUT_MS,
) -> None:
    """``dispatch=True`` fires an untrusted DOM event — driver rule 2's opt-out,
    for overlays that real input cannot reach."""
    behavior = behavior_for(session, humanize)
    with paced(behavior, session.behavior_runtime):
        click_element(
            session,
            session.find(selector, timeout=timeout),
            dispatch=dispatch,
            behavior=behavior,
        )


def click_element(
    session: "BrowserSession",
    element: Any,
    *,
    dispatch: bool = False,
    behavior: Behavior | None = None,
) -> None:
    """Click an element the caller already resolved.

    The one place the humanized-vs-plain-vs-dispatch choice is made, so a
    session method that found its element some other way — ``pick`` walking a
    list, ``download_file`` arming a download — clicks like every other click.
    Pacing belongs to whoever opened the action, not here.
    """
    behavior = behavior if behavior is not None else session.behavior
    if dispatch:
        session.driver.dispatch_event(element, "click")
    elif behavior.mouse_move:
        session.driver.humanized_click(
            session.get_page(), element, behavior, session.behavior_runtime
        )
    else:
        click_or_centre_and_retry(session, element)


DISPATCH_HINT = "still intercepted after scrolling it into view; try dispatch: true"

# What a driver says when something else took the click. Playwright reports
# `<div …> intercepts pointer events`, and `subtree intercepts pointer events`
# when the thief is a descendant of the target.
INTERCEPTION_MARKER = "intercepts pointer events"


def is_interception(exc: Exception) -> bool:
    """Whether the click failed because something covered the target.

    The only failure centring the element can fix. A disabled control, a
    hidden one, a selector that matched nothing: retrying those buys a second
    timeout and, worse, a `dispatch: true` hint that would fire an untrusted
    click at a control the page is deliberately refusing.
    """
    return INTERCEPTION_MARKER in str(exc)


def click_or_centre_and_retry(session: "BrowserSession", element: Any) -> None:
    """A click a fixed header or footer swallowed is worth one more try.

    Drivers scroll a target just far enough to be in view, which is exactly
    where a sticky banner sits; centring it moves it clear. A second
    interception is reported as the first one plus the escape hatch, because
    the original error is what says *why* the click never landed.
    """
    # debt: `Driver.click` takes no timeout, so the retry pays the driver's
    # own default a second time; plumb the step timeout through to bound it.
    intercepted = failed_click(session, element)
    if intercepted is None:
        return
    if not is_interception(intercepted):
        raise intercepted
    centre(session, element, intercepted)
    retried = failed_click(session, element)
    if retried is None:
        return
    if not is_interception(retried):
        raise retried
    failure = TimeoutError if is_timeout(intercepted) else ValueError
    raise failure(f"{intercepted}; {DISPATCH_HINT}") from intercepted


def centre(session: "BrowserSession", element: Any, intercepted: Exception) -> None:
    """Centre the element for the retry; a failure here is not the caller's
    problem. Centring is an evaluate against an element the click already
    struggled with, so it can time out on its own — reporting *that* would
    bury the click error the caller needs."""
    try:
        session.driver.scroll_into_view(element)
    except Exception as exc:
        logger.debug("could not centre the element for a click retry: %s", exc)
        raise intercepted from exc


def failed_click(session: "BrowserSession", element: Any) -> Exception | None:
    """The step failure the click raised, or ``None`` if it landed. A library
    bug is not a step failure and still propagates."""
    try:
        session.driver.click(element)
    except Exception as exc:
        if not is_step_failure(exc):
            raise
        return exc
    return None


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
    delay_ms: int | Jitter = 0,
    humanize: bool | None = None,
    timeout: int = DEFAULT_FIND_TIMEOUT_MS,
) -> None:
    """An explicit ``delay_ms`` is the caller's own cadence, so it wins over the
    behaviour's: a constant types at a constant rate, a :class:`Jitter` becomes
    the per-key delay of the humanized path."""
    behavior = behavior_for(session, humanize)
    with paced(behavior, session.behavior_runtime):
        element = session.find(selector, timeout=timeout)
        if isinstance(delay_ms, Jitter):
            jittered = behavior.model_copy(update={"type_char_delay": delay_ms})
            type_humanized(session, element, value, jittered)
        elif delay_ms > 0 or behavior.type_char_delay.max_ms == 0:
            session.driver.type(element, value, delay_ms=delay_ms)
        else:
            type_humanized(session, element, value, behavior)


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
        element = session.find(selector, timeout=timeout)
        expect_select(session, element, selector)
        session.driver.select_option(element, value)


def expect_select(session: "BrowserSession", element: Any, selector: Selector) -> None:
    """`select` on something that is not a `<select>` is a step error.

    Left to the drivers it is not: Playwright raises its own `Error`, which
    `execute_action` does not convert, so the flow died instead of returning
    a `FlowError` an `optional:` step could swallow. Asking the page costs one
    read and gives every driver the same message.

    A `<label>` answers for the control it labels, because the Playwright
    family resolves one before acting and this check must not reject a target
    those drivers accept.
    """
    tag = str(session.driver.evaluate(element, select_control_tag_js())).lower()
    if tag != "select":
        raise ValueError(
            f"select needs a <select>; {describe_selector(selector)} is a <{tag}>"
        )


def set_checked(
    session: "BrowserSession",
    selector: Selector,
    checked: bool,
    *,
    timeout: int = DEFAULT_FIND_TIMEOUT_MS,
) -> None:
    with paced(session.behavior, session.behavior_runtime):
        session.driver.set_checked(session.find(selector, timeout=timeout), checked)


def type_humanized(
    session: "BrowserSession",
    element: Any,
    value: str,
    behavior: Behavior | None = None,
) -> None:
    session.driver.humanized_type(
        session.get_page(),
        element,
        value,
        behavior if behavior is not None else session.behavior,
        session.behavior_runtime,
    )
