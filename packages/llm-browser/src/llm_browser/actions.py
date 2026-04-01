"""Action registry: 11 minimal declarative actions for browser automation."""

from functools import lru_cache
from typing import Any, Callable

from yaml_engine.registry import Registry

from llm_browser.models import Step
from llm_browser.session import BrowserSession

ActionHandler = Callable[[BrowserSession, Step], Any]


@lru_cache(maxsize=1)
def get_registry() -> Registry[ActionHandler]:
    return Registry("action")


register_action = get_registry().register


def execute_action(session: BrowserSession, step: Step) -> Any:
    """Dispatch a step's action to the appropriate handler."""
    if step.action is None:
        return None
    return get_registry().get(step.action)(session, step)


# --- Element actions ---


@register_action("click")
def action_click(session: BrowserSession, step: Step) -> None:
    assert step.selector is not None
    session.find(step.selector).click()


@register_action("fill")
def action_fill(session: BrowserSession, step: Step) -> None:
    assert step.selector is not None
    value: str = getattr(step, "value", "")
    session.find(step.selector).fill(value)


@register_action("type")
def action_type(session: BrowserSession, step: Step) -> None:
    assert step.selector is not None
    value: str = getattr(step, "value", "")
    delay: int = getattr(step, "delay", 0) or 0
    session.find(step.selector).type(value, delay=delay)


@register_action("select")
def action_select(session: BrowserSession, step: Step) -> None:
    assert step.selector is not None
    value: str = getattr(step, "value", "")
    session.find(step.selector).select_option(value)


@register_action("check")
def action_check(session: BrowserSession, step: Step) -> None:
    assert step.selector is not None
    checked: bool = getattr(step, "checked", True)
    element = session.find(step.selector)
    if checked:
        element.check()
    else:
        element.uncheck()


@register_action("pick")
def action_pick(session: BrowserSession, step: Step) -> None:
    assert step.selector is not None
    value: str = getattr(step, "value", "")
    session.pick(step.selector, value)


# --- Page actions ---


@register_action("goto")
def action_goto(session: BrowserSession, step: Step) -> None:
    url: str = getattr(step, "url", "")
    wait_until: str = (
        getattr(step, "wait_until", "domcontentloaded") or "domcontentloaded"
    )
    session.goto(url, wait_until=wait_until)


@register_action("wait")
def action_wait(session: BrowserSession, step: Step) -> None:
    state: str = getattr(step, "state", "domcontentloaded") or "domcontentloaded"
    timeout: int = getattr(step, "timeout", 10_000) or 10_000
    session.wait_for_load_state(state, timeout=timeout)


@register_action("screenshot")
def action_screenshot(session: BrowserSession, step: Step) -> str:
    return str(session.take_screenshot())


# --- Data actions ---


@register_action("read")
def action_read(session: BrowserSession, step: Step) -> list[dict[str, str | None]]:
    assert step.selector is not None
    extract: dict[str, dict[str, str]] = getattr(step, "extract", {})
    return session.parse_elements(step.selector, extract)


@register_action("dom")
def action_dom(session: BrowserSession, step: Step) -> str:
    assert step.selector is not None
    max_depth: int = getattr(step, "max_depth", 0) or 0
    return session.dom(step.selector, max_depth=max_depth)
