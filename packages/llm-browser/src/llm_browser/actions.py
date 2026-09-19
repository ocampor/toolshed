"""Action registry: minimal declarative actions for browser automation.

One handler per action, each taking the behaviour the step resolved to.
Importing this module is what registers them; :mod:`llm_browser.action_dispatch`
holds the registry and runs them.
"""

import time

from pydantic import BaseModel

from llm_browser.action_dispatch import (
    ActionHandler,
    execute_action,
    get_registry,
    step_behavior,
)
from llm_browser.behavior import Behavior, Jitter, jittered_sleep
from llm_browser.models import (
    CheckStep,
    CleanStep,
    ClickStep,
    DomStep,
    DownloadStep,
    FillStep,
    GotoStep,
    ParseStep,
    PickStep,
    PressStep,
    ReadStep,
    ScreenshotStep,
    ScrollStep,
    SelectStep,
    ThinkStep,
    TypeStep,
    WaitForStep,
)
from llm_browser.parse import build_model
from llm_browser.results import (
    BytesResult,
    ExtractedRow,
    ParsedResult,
    TextResult,
    VoidResult,
    is_step_failure,
)
from llm_browser.selectors import ScopedSelector, describe_selector
from llm_browser.session import BrowserSession

__all__ = [
    "ActionHandler",
    "execute_action",
    "get_registry",
    "is_step_failure",
    "step_behavior",
]

_registry = get_registry()


# --- Element actions ---


@_registry.register("click")
def action_click(
    session: BrowserSession, step: ClickStep, behavior: Behavior
) -> VoidResult:
    session.click(
        step.selector,
        dispatch=step.dispatch,
        behavior=behavior,
        timeout=step.timeout,
    )
    return VoidResult()


@_registry.register("fill")
def action_fill(
    session: BrowserSession, step: FillStep, behavior: Behavior
) -> VoidResult:
    session.fill(
        step.selector,
        step.value,
        verify=step.verify,
        behavior=behavior,
        timeout=step.timeout,
    )
    return VoidResult()


@_registry.register("clean")
def action_clean(
    session: BrowserSession, step: CleanStep, behavior: Behavior
) -> VoidResult:
    session.clean(step.selector, behavior=behavior, timeout=step.timeout)
    return VoidResult()


@_registry.register("type")
def action_type(
    session: BrowserSession, step: TypeStep, behavior: Behavior
) -> VoidResult:
    session.type(
        step.selector,
        step.value,
        delay_ms=step.delay,
        behavior=behavior,
        timeout=step.timeout,
    )
    return VoidResult()


@_registry.register("select")
def action_select(
    session: BrowserSession, step: SelectStep, behavior: Behavior
) -> VoidResult:
    session.select_option(
        step.selector, step.value, behavior=behavior, timeout=step.timeout
    )
    return VoidResult()


@_registry.register("check")
def action_check(
    session: BrowserSession, step: CheckStep, behavior: Behavior
) -> VoidResult:
    session.set_checked(
        step.selector, step.checked, behavior=behavior, timeout=step.timeout
    )
    return VoidResult()


@_registry.register("pick")
def action_pick(
    session: BrowserSession, step: PickStep, behavior: Behavior
) -> VoidResult:
    session.pick(step.selector, step.value, behavior=behavior)
    return VoidResult()


@_registry.register("press")
def action_press(
    session: BrowserSession, step: PressStep, behavior: Behavior
) -> VoidResult:
    session.press(step.selector, step.key, behavior=behavior, timeout=step.timeout)
    return VoidResult()


# --- Page actions ---


@_registry.register("goto")
def action_goto(
    session: BrowserSession, step: GotoStep, behavior: Behavior
) -> VoidResult:
    session.goto(step.url, wait_until=step.wait_until)
    return VoidResult()


@_registry.register("wait_for")
def action_wait_for(
    session: BrowserSession, step: WaitForStep, behavior: Behavior
) -> VoidResult:
    """A timeout here rides ``execute_action``'s handler: the step fails with
    the selector/state message, and ``optional: true`` turns it into a skip."""
    if step.value is not None and step.selector is not None:
        session.wait_for_value(
            step.selector,
            step.value,
            exact=step.exact,
            timeout=step.timeout,
            interval=step.interval,
        )
    elif step.text is not None:
        session.wait_for_text(
            step.text,
            selector=step.selector,
            exact=step.exact,
            state=step.state,
            timeout=step.timeout,
            interval=step.interval,
        )
    elif step.selector is not None:
        session.wait_for_element(
            step.selector,
            state=step.state,
            timeout=step.timeout,
            interval=step.interval,
            settle=step.settle,
        )
    else:
        raise ValueError("wait_for needs a selector or text")
    return VoidResult()


@_registry.register("screenshot")
def action_screenshot(
    session: BrowserSession, step: ScreenshotStep, behavior: Behavior
) -> BytesResult:
    """``step.path`` is not consulted: the runner returns the PNG and the CLI
    is what writes it."""
    return BytesResult(
        name=f"{step.name}.png",
        content=session.screenshot_bytes(step.selector),
        media_type="image/png",
    )


# --- Data actions ---


@_registry.register("read")
def action_read(
    session: BrowserSession, step: ReadStep, behavior: Behavior
) -> ParsedResult:
    raw = session.parse_elements(
        step.selector, step.extract, step.exclude, step.timeout
    )
    # debt: `expect: 1` already states this; the match rule should raise it,
    # with the samples and hint a bare ValueError cannot carry.
    if not raw and isinstance(step.selector, ScopedSelector):
        raise ValueError(
            f"read found nothing at {describe_selector(step.selector)}; "
            "the element does not carry it"
        )
    rows: list[BaseModel | None] = [
        ExtractedRow(**row) if any(v is not None for v in row.values()) else None
        for row in raw
    ]
    return ParsedResult(rows=rows)


@_registry.register("parse")
def action_parse(
    session: BrowserSession, step: ParseStep, behavior: Behavior
) -> ParsedResult:
    # Schema path is CWD-relative or absolute.
    Model = build_model(step.schema_path)  # type: ignore[no-untyped-call]
    raw = session.parse_elements(step.selector, Model._spec(), timeout=step.timeout)
    rows: list[BaseModel | None] = [
        Model.model_validate(row) if any(v is not None for v in row.values()) else None
        for row in raw
    ]
    return ParsedResult(rows=rows)


@_registry.register("dom")
def action_dom(
    session: BrowserSession, step: DomStep, behavior: Behavior
) -> TextResult:
    return TextResult(
        text=session.dom(step.selector, max_depth=step.max_depth, level=step.level)
    )


# --- File actions ---


@_registry.register("download")
def action_download(
    session: BrowserSession, step: DownloadStep, behavior: Behavior
) -> BytesResult:
    """``step.path`` is not consulted: the runner returns the bytes and the
    CLI is what writes them."""
    return session.download_file(step.selector, behavior=behavior, timeout=step.timeout)


# --- Pacing actions ---


@_registry.register("scroll")
def action_scroll(
    session: BrowserSession, step: ScrollStep, behavior: Behavior
) -> VoidResult:
    for tick in range(step.times):
        session.scroll(0, step.delta, behavior=behavior)
        if tick < step.times - 1:
            jittered_sleep(step.pause)
    return VoidResult()


@_registry.register("think")
def action_think(
    session: BrowserSession, step: ThinkStep, behavior: Behavior
) -> VoidResult:
    jitter = Jitter(min_ms=step.min_ms, max_ms=step.max_ms)
    delay = jitter.sample_seconds()
    if delay > 0:
        time.sleep(delay)
    return VoidResult()
