"""Action registry: minimal declarative actions for browser automation."""

import time
from functools import lru_cache
from typing import Callable

from pydantic import BaseModel, SerializeAsAny

from yaml_engine.registry import Registry

from llm_browser.behavior import Jitter, jittered_sleep, paced
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
    Step,
    ThinkStep,
    TypeStep,
    WaitForStep,
)
from llm_browser.parse import build_model
from llm_browser.paths import prepare_output_path
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

    rows: list[SerializeAsAny[BaseModel] | None]


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


def _is_timeout(exc: BaseException) -> bool:
    """Treat any exception class named ``TimeoutError`` as a timeout.
    Patchright (and similar driver libs) raise their own TimeoutError
    that does NOT inherit from the Python builtin, so a bare
    ``isinstance(exc, TimeoutError)`` check misses driver-side waits
    and the optional-swallow / ErrorResult contract was violated."""
    if isinstance(exc, TimeoutError):
        return True
    return type(exc).__name__ == "TimeoutError"


def execute_action(session: BrowserSession, step: Step) -> ActionResult:
    if step.action is None:
        return VoidResult()
    try:
        with paced(session.behavior, session.behavior_runtime):
            return get_registry().get(step.action)(session, step)
    except Exception as exc:
        if not (_is_timeout(exc) or isinstance(exc, ValueError)):
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
def action_screenshot(session: BrowserSession, step: ScreenshotStep) -> PathResult:
    if step.path:
        out = prepare_output_path(step.path)
        session.save_screenshot(out)
        return PathResult(path=str(out))
    return PathResult(path=str(session.take_screenshot()))


# --- Data actions ---


@_registry.register("read")
def action_read(session: BrowserSession, step: ReadStep) -> ParsedResult:
    raw = session.parse_elements(step.selector, step.extract)
    rows: list[BaseModel | None] = [
        ExtractedRow(**row) if any(v is not None for v in row.values()) else None
        for row in raw
    ]
    result = ParsedResult(rows=rows)
    if step.path:
        _write_rows(step.path, result)
    return result


@_registry.register("parse")
def action_parse(session: BrowserSession, step: ParseStep) -> ParsedResult:
    # Schema path is CWD-relative or absolute (same convention as `download.path`).
    Model = build_model(step.schema_path)  # type: ignore[no-untyped-call]
    raw = session.parse_elements(step.selector, Model._spec())
    rows: list[BaseModel | None] = [
        Model.model_validate(row) if any(v is not None for v in row.values()) else None
        for row in raw
    ]
    result = ParsedResult(rows=rows)
    if step.path:
        _write_rows(step.path, result)
    return result


def _write_rows(path: str, result: ParsedResult) -> None:
    """JSON-dump ``ParsedResult.rows`` to ``path``. Rows are Pydantic models
    (or ``None``); use ``model_dump`` so dynamic-field ``ExtractedRow`` and
    typed ``ParseBase`` instances both serialize uniformly."""
    import json

    payload = [r.model_dump() if r is not None else None for r in result.rows]
    prepare_output_path(path).write_text(json.dumps(payload, ensure_ascii=False))


@_registry.register("dom")
def action_dom(session: BrowserSession, step: DomStep) -> TextResult:
    html = session.dom(step.selector, max_depth=step.max_depth)
    if step.path:
        prepare_output_path(step.path).write_text(html)
    return TextResult(text=html)


# --- File actions ---


@_registry.register("download")
def action_download(session: BrowserSession, step: DownloadStep) -> PathResult:
    return PathResult(path=str(session.download_file(step.selector, step.path)))


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
