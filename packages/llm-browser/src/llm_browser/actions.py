"""Action registry: 12 minimal declarative actions for browser automation."""

from functools import lru_cache
from typing import Any, Callable

from yaml_engine.registry import Registry

from llm_browser.models import (
    BaseStep,
    CheckStep,
    ClickStep,
    DomStep,
    DownloadStep,
    FillStep,
    GotoStep,
    PickStep,
    ReadStep,
    ScreenshotStep,
    SelectStep,
    Step,
    TypeStep,
    WaitStep,
)
from llm_browser.session import BrowserSession

ActionHandler = Callable[[BrowserSession, BaseStep], Any]


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
def action_click(session: BrowserSession, step: ClickStep) -> None:
    assert step.selector is not None
    session.find(step.selector).click()


@register_action("fill")
def action_fill(session: BrowserSession, step: FillStep) -> None:
    assert step.selector is not None
    session.find(step.selector).fill(step.value)


@register_action("type")
def action_type(session: BrowserSession, step: TypeStep) -> None:
    assert step.selector is not None
    session.find(step.selector).type(step.value, delay=step.delay)


@register_action("select")
def action_select(session: BrowserSession, step: SelectStep) -> None:
    assert step.selector is not None
    session.find(step.selector).select_option(step.value)


@register_action("check")
def action_check(session: BrowserSession, step: CheckStep) -> None:
    assert step.selector is not None
    element = session.find(step.selector)
    if step.checked:
        element.check()
    else:
        element.uncheck()


@register_action("pick")
def action_pick(session: BrowserSession, step: PickStep) -> None:
    assert step.selector is not None
    session.pick(step.selector, step.value)


# --- Page actions ---


@register_action("goto")
def action_goto(session: BrowserSession, step: GotoStep) -> None:
    session.goto(step.url, wait_until=step.wait_until)


@register_action("wait")
def action_wait(session: BrowserSession, step: WaitStep) -> None:
    session.wait_for_load_state(step.state, timeout=step.timeout)


@register_action("screenshot")
def action_screenshot(session: BrowserSession, step: ScreenshotStep) -> str:
    return str(session.take_screenshot())


# --- Data actions ---


@register_action("read")
def action_read(session: BrowserSession, step: ReadStep) -> list[dict[str, str | None]]:
    assert step.selector is not None
    return session.parse_elements(step.selector, step.extract)


@register_action("dom")
def action_dom(session: BrowserSession, step: DomStep) -> str:
    assert step.selector is not None
    return session.dom(step.selector, max_depth=step.max_depth)


# --- File actions ---


@register_action("download")
def action_download(session: BrowserSession, step: DownloadStep) -> str:
    assert step.selector is not None
    if not step.path:
        raise ValueError("download action requires 'path' field")
    return str(session.download_file(step.selector, step.path))
