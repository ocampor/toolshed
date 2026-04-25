"""Action registry: minimal declarative actions for browser automation."""

import time
from functools import lru_cache
from typing import Callable

from pydantic import BaseModel

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
    ParseStep,
    PickStep,
    PressStep,
    ReadStep,
    ScreenshotStep,
    SelectStep,
    Step,
    ThinkStep,
    TypeStep,
    WaitStep,
)
from llm_browser.parse import build_model
from llm_browser.session import BrowserSession


class ActionResult(BaseModel):
    """Base for everything ``execute_action`` returns.

    All result subclasses inherit ``ok``: ``True`` for success/skip,
    ``False`` for ``ErrorResult``. The flow runner short-circuits when it
    sees a non-ok result.
    """

    ok: bool = True


class VoidResult(ActionResult):
    """Action succeeded with no payload (click, fill, select, press, ...)."""


class PathResult(ActionResult):
    """Action produced a file path on disk (screenshot, download)."""

    path: str


class TextResult(ActionResult):
    """Action produced inline text (dom, wait)."""

    text: str


class ExtractedRow(BaseModel, extra="allow"):
    """A single row of data extracted by ``read``. Field set is dynamic — keys
    come from the step's ``extract`` config; values are ``str`` or ``None``.
    Modeled with ``extra='allow'`` so it serializes uniformly while staying
    schema-free.
    """


class ParsedResult(ActionResult):
    """Action extracted structured rows.

    For ``read`` action: rows are ``ExtractedRow`` (dynamic-fields BaseModel),
    or ``None`` if every field was empty for that row.

    For ``parse`` action: rows are typed instances of the schema model
    (``ParseBase`` subclass), with values coerced by Pydantic.
    """

    model_config = {"arbitrary_types_allowed": True}

    rows: list[BaseModel | None]


class SkippedResult(ActionResult):
    """Optional step was skipped because its action raised an expected error.
    ``ok`` stays True — a skip is a successful no-op."""

    skipped: bool = True
    reason: str


class ErrorResult(ActionResult):
    """Action failed with an expected runtime error (Timeout/Value).

    Returned (not raised) so the flow runner can short-circuit cleanly and
    the CLI can emit structured JSON without unwinding through Python's
    exception machinery. Truly unexpected exceptions still propagate.
    """

    ok: bool = False
    error: str
    message: str
    step_name: str
    selector: str | None = None
    hint: str | None = None


# Param type is loose because each handler accepts a specific Step subclass, and
# Callable parameters are contravariant. The discriminated Step union dispatches
# at runtime via the registry, so this widening only affects static typing.
ActionHandler = Callable[..., ActionResult]


@lru_cache(maxsize=1)
def get_registry() -> Registry[ActionHandler]:
    return Registry("action")


_registry = get_registry()


def execute_action(session: BrowserSession, step: Step) -> ActionResult:
    if step.action is None:
        return VoidResult()
    behavior = session.behavior
    runtime = session._behavior_runtime
    enforce_gap(behavior, runtime)
    try:
        result: ActionResult = get_registry().get(step.action)(session, step)
    except (TimeoutError, ValueError) as exc:
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
                if isinstance(exc, TimeoutError)
                else None
            ),
        )
    post_pause(behavior, runtime)
    mark_action_done(runtime)
    return result


# --- Element actions ---


@_registry.register("click")
def action_click(session: BrowserSession, step: ClickStep) -> VoidResult:
    element = session.find(step.selector, timeout=step.timeout)
    if step.dispatch:
        session.driver.dispatch_event(element, "click")
    elif session.behavior.mouse_move:
        session.driver.humanized_click(
            session.get_page(), element, session.behavior, session._behavior_runtime
        )
    else:
        session.driver.click(element)
    return VoidResult()


@_registry.register("fill")
def action_fill(session: BrowserSession, step: FillStep) -> VoidResult:
    element = session.find(step.selector, timeout=step.timeout)
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
    return VoidResult()


@_registry.register("type")
def action_type(session: BrowserSession, step: TypeStep) -> VoidResult:
    element = session.find(step.selector, timeout=step.timeout)
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
    return VoidResult()


@_registry.register("select")
def action_select(session: BrowserSession, step: SelectStep) -> VoidResult:
    element = session.find(step.selector, timeout=step.timeout)
    session.driver.select_option(element, step.value)
    return VoidResult()


@_registry.register("check")
def action_check(session: BrowserSession, step: CheckStep) -> VoidResult:
    element = session.find(step.selector, timeout=step.timeout)
    session.driver.set_checked(element, step.checked)
    return VoidResult()


@_registry.register("pick")
def action_pick(session: BrowserSession, step: PickStep) -> VoidResult:
    session.pick(step.selector, step.value)
    return VoidResult()


@_registry.register("press")
def action_press(session: BrowserSession, step: PressStep) -> VoidResult:
    if session.behavior.mouse_move:
        jittered_sleep(session.behavior.pre_click_pause, session._behavior_runtime.rng)
    if step.selector is not None:
        element = session.find(step.selector, timeout=step.timeout)
        session.driver.press(element, step.key)
    else:
        session.driver.press_focused(session.get_page(), step.key)
    return VoidResult()


# --- Page actions ---


@_registry.register("goto")
def action_goto(session: BrowserSession, step: GotoStep) -> VoidResult:
    session.goto(step.url, wait_until=step.wait_until)
    return VoidResult()


@_registry.register("wait")
def action_wait(session: BrowserSession, step: WaitStep) -> TextResult:
    text = session.wait_until_stable(
        step.selector,
        quiet_ms=step.quiet_ms,
        timeout_s=step.timeout_s,
    )
    return TextResult(text=text)


@_registry.register("screenshot")
def action_screenshot(session: BrowserSession, step: ScreenshotStep) -> PathResult:
    return PathResult(path=str(session.take_screenshot()))


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
    # Schema path is CWD-relative or absolute (same convention as `download.path`).
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
def action_download(session: BrowserSession, step: DownloadStep) -> PathResult:
    return PathResult(path=str(session.download_file(step.selector, step.path)))


# --- Pacing actions ---


@_registry.register("think")
def action_think(session: BrowserSession, step: ThinkStep) -> VoidResult:
    jitter = Jitter(min_ms=step.min_ms, max_ms=step.max_ms)
    delay = jitter.sample_seconds(session._behavior_runtime.rng)
    if delay > 0:
        time.sleep(delay)
    return VoidResult()
