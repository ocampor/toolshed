"""Action registry: minimal declarative actions for browser automation."""

import time
from functools import lru_cache
from typing import Any, Callable

from yaml_engine.registry import Registry

from llm_browser.behavior import (
    Jitter,
    enforce_gap,
    jittered_sleep,
    mark_action_done,
    post_pause,
)
from llm_browser.models import (
    CheckStep,
    ClickStep,
    DomStep,
    DownloadStep,
    FillStep,
    GotoStep,
    PickStep,
    PressStep,
    ReadStep,
    ScreenshotStep,
    SelectStep,
    Step,
    ThinkStep,
    TypeStep,
    WaitStableStep,
    WaitStep,
)
from llm_browser.session import BrowserSession

ActionHandler = Callable[..., Any]


@lru_cache(maxsize=1)
def get_registry() -> Registry[ActionHandler]:
    return Registry("action")


_registry = get_registry()


def execute_action(session: BrowserSession, step: Step) -> Any:
    if step.action is None:
        return None
    behavior = session.behavior
    runtime = session._behavior_runtime
    enforce_gap(behavior, runtime)
    result = get_registry().get(step.action)(session, step)
    post_pause(behavior, runtime)
    mark_action_done(runtime)
    return result


# --- Element actions ---


@_registry.register("click")
def action_click(session: BrowserSession, step: ClickStep) -> None:
    assert step.selector is not None
    element = session.find(step.selector)
    if step.dispatch:
        session.driver.dispatch_event(element, "click")
    elif session.behavior.mouse_move:
        session.driver.humanized_click(
            session.get_page(), element, session.behavior, session._behavior_runtime
        )
    else:
        session.driver.click(element)


@_registry.register("fill")
def action_fill(session: BrowserSession, step: FillStep) -> None:
    assert step.selector is not None
    element = session.find(step.selector)
    if session.behavior.fill_as_type:
        session.driver.humanized_type(
            session.get_page(),
            element,
            step.value,
            session.behavior,
            session._behavior_runtime,
        )
    else:
        session.driver.fill(element, step.value)


@_registry.register("type")
def action_type(session: BrowserSession, step: TypeStep) -> None:
    assert step.selector is not None
    element = session.find(step.selector)
    if step.delay > 0 or session.behavior.type_char_delay.max_ms == 0:
        session.driver.type(element, step.value, delay_ms=step.delay)
    else:
        session.driver.humanized_type(
            session.get_page(),
            element,
            step.value,
            session.behavior,
            session._behavior_runtime,
        )


@_registry.register("select")
def action_select(session: BrowserSession, step: SelectStep) -> None:
    assert step.selector is not None
    session.driver.select_option(session.find(step.selector), step.value)


@_registry.register("check")
def action_check(session: BrowserSession, step: CheckStep) -> None:
    assert step.selector is not None
    session.driver.set_checked(session.find(step.selector), step.checked)


@_registry.register("pick")
def action_pick(session: BrowserSession, step: PickStep) -> None:
    assert step.selector is not None
    session.pick(step.selector, step.value)


@_registry.register("press")
def action_press(session: BrowserSession, step: PressStep) -> None:
    if not step.key:
        raise ValueError("press action requires 'key' field")
    if session.behavior.mouse_move:
        jittered_sleep(session.behavior.pre_click_pause, session._behavior_runtime.rng)
    if step.selector is not None:
        element = session.find(step.selector)
        session.driver.press(element, step.key)
    else:
        session.driver.press_focused(session.get_page(), step.key)


# --- Page actions ---


@_registry.register("goto")
def action_goto(session: BrowserSession, step: GotoStep) -> None:
    session.goto(step.url, wait_until=step.wait_until)


@_registry.register("wait")
def action_wait(session: BrowserSession, step: WaitStep) -> None:
    session.wait_for_load_state(step.state, timeout=step.timeout)


@_registry.register("wait_stable")
def action_wait_stable(session: BrowserSession, step: WaitStableStep) -> str:
    assert step.selector is not None
    return session.wait_until_stable(
        step.selector,
        quiet_ms=step.quiet_ms,
        timeout_s=step.timeout_s,
    )


@_registry.register("screenshot")
def action_screenshot(session: BrowserSession, step: ScreenshotStep) -> str:
    return str(session.take_screenshot())


# --- Data actions ---


@_registry.register("read")
def action_read(session: BrowserSession, step: ReadStep) -> list[dict[str, str | None]]:
    assert step.selector is not None
    return session.parse_elements(step.selector, step.extract)


@_registry.register("dom")
def action_dom(session: BrowserSession, step: DomStep) -> str:
    assert step.selector is not None
    return session.dom(step.selector, max_depth=step.max_depth)


# --- File actions ---


@_registry.register("download")
def action_download(session: BrowserSession, step: DownloadStep) -> str:
    assert step.selector is not None
    if not step.path:
        raise ValueError("download action requires 'path' field")
    return str(session.download_file(step.selector, step.path))


# --- Pacing actions ---


@_registry.register("think")
def action_think(session: BrowserSession, step: ThinkStep) -> None:
    jitter = Jitter(min_ms=step.min_ms, max_ms=step.max_ms)
    delay = jitter.sample_seconds(session._behavior_runtime.rng)
    if delay > 0:
        time.sleep(delay)
