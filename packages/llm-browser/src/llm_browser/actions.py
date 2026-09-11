"""Action registry: minimal declarative actions for browser automation."""

import time
from functools import lru_cache
from typing import Callable

from pydantic import BaseModel

from yaml_engine.registry import Registry

from llm_browser.behavior import Jitter, jittered_sleep, paced
from llm_browser.captcha import solve as solve_captcha
from llm_browser.models import (
    CheckStep,
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
    SolveCaptchaStep,
    Step,
    ThinkStep,
    TypeStep,
    WaitForStep,
)
from llm_browser.parse import build_model
from llm_browser.results import (
    ActionResult,
    BytesResult,
    ErrorResult,
    ExtractedRow,
    ParsedResult,
    SkippedResult,
    TextResult,
    VoidResult,
)
from llm_browser.session import BrowserSession


# Param type is loose because each handler accepts a specific Step subclass, and
# Callable parameters are contravariant. The discriminated Step union dispatches
# at runtime via the registry, so this widening only affects static typing.
ActionHandler = Callable[..., ActionResult]


@lru_cache(maxsize=1)
def get_registry() -> Registry[ActionHandler]:
    return Registry("action")


_registry = get_registry()


def _is_timeout(exc: BaseException) -> bool:
    """Treat any exception class named ``TimeoutError`` as a timeout.
    Patchright (and similar driver libs) raise their own TimeoutError
    that does NOT inherit from the Python builtin, so a bare
    ``isinstance(exc, TimeoutError)`` check misses driver-side waits
    and the optional-swallow / ErrorResult contract was violated."""
    if isinstance(exc, TimeoutError):
        return True
    return type(exc).__name__ == "TimeoutError"


def is_step_failure(exc: BaseException) -> bool:
    """Whether ``exc`` is a step result rather than a library bug.

    Deliberately narrow. Anything a step can legitimately hit — a wait that
    expired, a value the page did not provide, an output it cannot write — is
    raised as one of these two at the place it happens. A ``TypeError`` or an
    ``AttributeError`` reaching here is a bug in the library, and it belongs
    in a traceback rather than in a truncated ``reason=`` on a skipped step.
    """
    return _is_timeout(exc) or isinstance(exc, ValueError)


def execute_action(session: BrowserSession, step: Step) -> ActionResult:
    if step.action is None:
        return VoidResult()
    try:
        with paced(session.behavior, session.behavior_runtime):
            return get_registry().get(step.action)(session, step)
    except Exception as exc:
        if not is_step_failure(exc):
            raise
        if step.optional:
            return SkippedResult(reason=f"{type(exc).__name__}: {str(exc)[:200]}")
        selector = getattr(step, "selector", None)
        return ErrorResult(
            error=type(exc).__name__,
            # Collapse whitespace so multi-line errors (Pydantic ValidationError,
            # patchright tracebacks) survive the 300-char cap meaningfully.
            message=" ".join(str(exc).split())[:300],
            step_name=step.name,
            selector=repr(selector) if selector is not None else None,
            hint=(
                "element hidden, missing, or slow to render"
                if _is_timeout(exc)
                else None
            ),
        )


# --- Element actions ---


@_registry.register("click")
def action_click(session: BrowserSession, step: ClickStep) -> VoidResult:
    session.click(step.selector, dispatch=step.dispatch, timeout=step.timeout)
    return VoidResult()


@_registry.register("fill")
def action_fill(session: BrowserSession, step: FillStep) -> VoidResult:
    session.fill(step.selector, step.value, timeout=step.timeout)
    return VoidResult()


@_registry.register("type")
def action_type(session: BrowserSession, step: TypeStep) -> VoidResult:
    session.type(step.selector, step.value, delay_ms=step.delay, timeout=step.timeout)
    return VoidResult()


@_registry.register("select")
def action_select(session: BrowserSession, step: SelectStep) -> VoidResult:
    session.select_option(step.selector, step.value, timeout=step.timeout)
    return VoidResult()


@_registry.register("check")
def action_check(session: BrowserSession, step: CheckStep) -> VoidResult:
    session.set_checked(step.selector, step.checked, timeout=step.timeout)
    return VoidResult()


@_registry.register("pick")
def action_pick(session: BrowserSession, step: PickStep) -> VoidResult:
    session.pick(step.selector, step.value)
    return VoidResult()


@_registry.register("press")
def action_press(session: BrowserSession, step: PressStep) -> VoidResult:
    session.press(step.selector, step.key, timeout=step.timeout)
    return VoidResult()


# --- Page actions ---


@_registry.register("goto")
def action_goto(session: BrowserSession, step: GotoStep) -> VoidResult:
    session.goto(step.url, wait_until=step.wait_until)
    return VoidResult()


@_registry.register("wait_for")
def action_wait_for(session: BrowserSession, step: WaitForStep) -> VoidResult:
    """A timeout here rides ``execute_action``'s handler: the step fails with
    the selector/state message, and ``optional: true`` turns it into a skip."""
    session.wait_for_element(
        step.selector,
        state=step.state,
        timeout=step.timeout,
        interval=step.interval,
        settle=step.settle,
    )
    return VoidResult()


@_registry.register("screenshot")
def action_screenshot(session: BrowserSession, step: ScreenshotStep) -> BytesResult:
    """``step.path`` is not consulted: the runner returns the PNG and the CLI
    is what writes it."""
    return BytesResult(
        name=f"{step.name}.png",
        content=session.screenshot_bytes(step.selector),
        media_type="image/png",
    )


@_registry.register("solve_captcha")
def action_solve_captcha(
    session: BrowserSession, step: SolveCaptchaStep
) -> ActionResult:
    return solve_captcha(session, step)


# --- Data actions ---


@_registry.register("read")
def action_read(session: BrowserSession, step: ReadStep) -> ParsedResult:
    raw = session.parse_elements(step.selector, step.extract)
    rows: list[BaseModel | None] = [
        ExtractedRow(**row) if any(v is not None for v in row.values()) else None
        for row in raw
    ]
    return ParsedResult(rows=rows)


@_registry.register("parse")
def action_parse(session: BrowserSession, step: ParseStep) -> ParsedResult:
    # Schema path is CWD-relative or absolute.
    Model = build_model(step.schema_path)  # type: ignore[no-untyped-call]
    raw = session.parse_elements(step.selector, Model._spec())
    rows: list[BaseModel | None] = [
        Model.model_validate(row) if any(v is not None for v in row.values()) else None
        for row in raw
    ]
    return ParsedResult(rows=rows)


@_registry.register("dom")
def action_dom(session: BrowserSession, step: DomStep) -> TextResult:
    return TextResult(text=session.dom(step.selector, max_depth=step.max_depth))


# --- File actions ---


@_registry.register("download")
def action_download(session: BrowserSession, step: DownloadStep) -> BytesResult:
    """``step.path`` is not consulted: the runner returns the bytes and the
    CLI is what writes them."""
    return session.download_file(step.selector, timeout=step.timeout)


# --- Pacing actions ---


@_registry.register("scroll")
def action_scroll(session: BrowserSession, step: ScrollStep) -> VoidResult:
    for tick in range(step.times):
        session.scroll(0, step.delta)
        if tick < step.times - 1:
            jittered_sleep(step.pause, session.behavior_runtime.rng)
    return VoidResult()


@_registry.register("think")
def action_think(session: BrowserSession, step: ThinkStep) -> VoidResult:
    jitter = Jitter(min_ms=step.min_ms, max_ms=step.max_ms)
    delay = jitter.sample_seconds(session.behavior_runtime.rng)
    if delay > 0:
        time.sleep(delay)
    return VoidResult()
