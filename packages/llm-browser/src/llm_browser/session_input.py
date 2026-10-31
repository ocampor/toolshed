"""Callers above the session use these, never the driver."""

import logging
from typing import TYPE_CHECKING, Any, NamedTuple

from llm_browser.behavior import (
    WHEEL_SETTLE_PAUSE,
    Behavior,
    HitTest,
    Jitter,
    jittered_delta,
    jittered_point,
    jittered_sleep,
    move_mouse_to,
    paced,
    path_steps,
)
from llm_browser.constants import (
    DEFAULT_FIND_TIMEOUT_MS,
    HIT_TEST_TIMEOUT_MS,
    LOGGER_NAME,
    WHEEL_INTO_VIEW_TICKS,
)
from llm_browser.results import HitTarget, is_step_failure, is_timeout
from llm_browser.scripts import hit_test_js, select_control_tag_js, viewport_fit_js
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
    """A driver config redefining a knob keeps it, or our path would stack on the driver's (camoufox's Bézier)."""
    declared = behavior.__class__.model_fields[field]
    return bool(declared.default != Behavior.model_fields[field].default)


def driver_opt_outs(session_behavior: Behavior) -> dict[str, Any]:
    """A session that set the knob itself overrules the driver."""
    declared = session_behavior.__class__.model_fields
    return {
        name: declared[name].default
        for name in Behavior.model_fields
        if driver_opt_out(session_behavior, name)
        and getattr(session_behavior, name) == declared[name].default
    }


def with_driver_opt_outs(session_behavior: Behavior, resolved: Behavior) -> Behavior:
    """One rule, applied last to whatever a call resolved to: a behaviour the
    caller wrote by hand cannot switch on what the driver humanizes itself."""
    opt_outs = driver_opt_outs(session_behavior)
    return resolved.model_copy(update=opt_outs) if opt_outs else resolved


def switched_on(behavior: Behavior) -> dict[str, Any]:
    """The knobs ``humanize: true`` turns on: those still sitting at their
    ``off()`` value. One the session tuned — a slower key delay, a tighter
    click offset — is already humanized the way its owner meant it to be."""
    human, off = Behavior.human(), Behavior.off()
    return {
        name: getattr(human, name)
        for name in HUMANIZE_KNOBS
        if getattr(behavior, name) == getattr(off, name)
    }


def switched_off() -> dict[str, Any]:
    return {name: getattr(Behavior.off(), name) for name in HUMANIZE_KNOBS}


def behavior_for(base: Behavior, humanize: bool | None) -> Behavior:
    """Timing included: a humanized action that pauses like an instant one is half humanized."""
    if humanize is None:
        return base
    knobs = switched_on(base) if humanize else switched_off()
    return base.model_copy(update=knobs)


def effective_behavior(
    session: "BrowserSession",
    humanize: bool | None = None,
    behavior: Behavior | None = None,
) -> Behavior:
    """Explicit ``behavior``, then the ``humanize`` shorthand, then the default; driver opt-outs last."""
    resolved = (
        behavior if behavior is not None else behavior_for(session.behavior, humanize)
    )
    return with_driver_opt_outs(session.behavior, resolved)


def click(
    session: "BrowserSession",
    selector: Selector,
    *,
    dispatch: bool = False,
    humanize: bool | None = None,
    behavior: Behavior | None = None,
    timeout: int = DEFAULT_FIND_TIMEOUT_MS,
) -> HitTarget | None:
    """``dispatch=True`` fires an untrusted DOM event — driver rule 2's opt-out,
    for overlays that real input cannot reach."""
    behavior = effective_behavior(session, humanize, behavior)
    with paced(behavior):
        return click_element(
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
    behavior: Behavior,
) -> HitTarget | None:
    """The one place the humanized/plain/dispatch choice is made; pacing belongs to the caller."""
    if dispatch:
        session.driver.dispatch_event(element, "click")
        return None
    if behavior.mouse_move:
        # The pointer can only be moved to a point in the viewport: an element
        # below the fold would be clicked at the clamped edge, on whatever sits
        # there. Drivers scroll for their own clicks; this path drives the
        # mouse itself, so it brings the target in first.
        wheel_into_view(session, element, behavior)
        return session.driver.humanized_click(
            session.get_page(),
            element,
            behavior,
            hit_test_after_move(session, element, behavior),
        )
    click_or_centre_and_retry(session, element)
    return None


def hit_test_after_move(
    session: "BrowserSession", element: Any, behavior: Behavior
) -> HitTest:
    """A menu the curve opened can cover the target, so the end point is re-asked; a check that cannot run refuses."""

    def check(point: tuple[float, float]) -> HitTarget | None:
        try:
            read = session.driver.evaluate(
                element, hit_test_js(point), timeout_ms=HIT_TEST_TIMEOUT_MS
            )
        except Exception as exc:
            retreat_pointer(session, element, behavior, point)
            raise ValueError(f"not actionable: hit-test-failed; {exc}") from exc
        if read["hit"] is None:
            return None
        hit = HitTarget.model_validate(read["hit"])
        if not read["target"]:
            retreat_pointer(session, element, behavior, point)
            raise ValueError(
                "not actionable: covered-after-move; the pointer path ended "
                f"over <{hit.tag} class={hit.class_name!r}> {hit.text!r}"
            )
        return hit

    return check


class ViewportFit(NamedTuple):
    gap: int
    centre: tuple[float, float]
    scroll_y: int


def viewport_fit(session: "BrowserSession", element: Any) -> ViewportFit:
    read = session.driver.evaluate(element, viewport_fit_js())
    x, y = read["centre"]
    return ViewportFit(
        gap=int(read["gap"]),
        centre=(float(x), float(y)),
        scroll_y=int(read["scrollY"]),
    )


def wheel_into_view(
    session: "BrowserSession", element: Any, behavior: Behavior
) -> None:
    """``scroll_into_view`` jumps in one frame with no wheel events, the tell this avoids; a tick that moves nothing stops the loop."""
    page = session.get_page()
    fit = viewport_fit(session, element)
    for _ in range(WHEEL_INTO_VIEW_TICKS):
        if fit.gap == 0:
            break
        try:
            session.driver.scroll(page, 0, jittered_delta(fit.gap, behavior))
        except NotImplementedError:
            break
        jittered_sleep(WHEEL_SETTLE_PAUSE)
        before = fit.scroll_y
        fit = viewport_fit(session, element)
        if fit.scroll_y == before:
            break
    if fit.gap == 0:
        return
    logger.debug("could not wheel %s into view; scrolling it in instead", element)
    session.driver.scroll_into_view(element)


def retreat_pointer(
    session: "BrowserSession",
    element: Any,
    behavior: Behavior,
    point: tuple[float, float],
) -> None:
    """A parked pointer keeps its menu open; the retreat point is jittered and best-effort."""
    try:
        fit = viewport_fit(session, element)
        destination = jittered_point(
            fit.centre, fit.centre, behavior.click_offset_ratio
        )
        move_mouse_to(
            session.get_page(), destination, max(1, path_steps(behavior) // 2), point
        )
    except Exception:
        logger.debug("could not retreat the pointer from %s", point, exc_info=True)


DISPATCH_HINT = "still intercepted after scrolling it into view; try dispatch: true"

# What a driver says when something else took the click. Playwright reports
# `<div …> intercepts pointer events`, and `subtree intercepts pointer events`
# when the thief is a descendant of the target.
INTERCEPTION_MARKER = "intercepts pointer events"


def is_interception(exc: Exception) -> bool:
    """Only an interception is fixed by centring; retrying anything else adds a timeout and a bad ``dispatch`` hint."""
    return INTERCEPTION_MARKER in str(exc)


def click_or_centre_and_retry(session: "BrowserSession", element: Any) -> None:
    """Drivers scroll a target just into view, where sticky banners sit; centring clears them."""
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
    """Centring can time out on the same element; reporting that would bury the click error."""
    try:
        session.driver.scroll_into_view(element)
    except Exception as exc:
        logger.debug("could not centre the element for a click retry: %s", exc)
        raise intercepted from exc


def failed_click(session: "BrowserSession", element: Any) -> Exception | None:
    """A library bug is not a step failure and still propagates."""
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
    humanize: bool | None = None,
    behavior: Behavior | None = None,
    timeout: int = DEFAULT_FIND_TIMEOUT_MS,
) -> None:
    behavior = effective_behavior(session, humanize, behavior)
    with paced(behavior):
        element = session.find(selector, timeout=timeout)
        if behavior.fill_as_type:
            type_humanized(session, element, value, behavior)
        else:
            session.driver.fill(element, value)


def type(  # shadows the builtin to mirror the `type` action's name
    session: "BrowserSession",
    selector: Selector,
    value: str,
    *,
    delay_ms: int | Jitter = 0,
    humanize: bool | None = None,
    behavior: Behavior | None = None,
    timeout: int = DEFAULT_FIND_TIMEOUT_MS,
) -> None:
    """An explicit ``delay_ms`` is the caller's cadence and wins over the behaviour's."""
    behavior = effective_behavior(session, humanize, behavior)
    with paced(behavior):
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
    behavior: Behavior | None = None,
    timeout: int = DEFAULT_FIND_TIMEOUT_MS,
) -> None:
    """``selector=None`` presses whatever holds focus."""
    behavior = effective_behavior(session, behavior=behavior)
    with paced(behavior):
        if behavior.mouse_move:
            jittered_sleep(behavior.pre_click_pause)
        if selector is None:
            session.driver.press_focused(session.get_page(), key)
            return
        session.driver.press(session.find(selector, timeout=timeout), key)


def select_option(
    session: "BrowserSession",
    selector: Selector,
    value: str,
    *,
    behavior: Behavior | None = None,
    timeout: int = DEFAULT_FIND_TIMEOUT_MS,
) -> None:
    with paced(effective_behavior(session, behavior=behavior)):
        element = session.find(selector, timeout=timeout)
        expect_select(session, element, selector)
        session.driver.select_option(element, value)


def expect_select(session: "BrowserSession", element: Any, selector: Selector) -> None:
    """Playwright's own `Error` here once killed the flow; asking the page gives every driver one message.
    A `<label>` answers for its control, as the Playwright family resolves it.
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
    behavior: Behavior | None = None,
    timeout: int = DEFAULT_FIND_TIMEOUT_MS,
) -> None:
    with paced(effective_behavior(session, behavior=behavior)):
        session.driver.set_checked(session.find(selector, timeout=timeout), checked)


def type_humanized(
    session: "BrowserSession",
    element: Any,
    value: str,
    behavior: Behavior,
) -> None:
    session.driver.humanized_type(session.get_page(), element, value, behavior)
