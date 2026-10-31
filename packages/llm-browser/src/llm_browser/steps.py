import logging
import time
from typing import Any, cast

from yaml_engine.compile import compile_condition
from yaml_engine.conditions import evaluate_condition
from yaml_engine.template import resolve_templates_in_dict

from llm_browser.actions import execute_action
from llm_browser.behavior import Behavior
from llm_browser.results import ActionResult, SkippedResult
from llm_browser.constants import LOGGER_NAME, WHEN_SKIP_REASON
from llm_browser.models import (
    FlowData,
    FlowError,
    Step,
    match_warning,
    validate_step,
)
from llm_browser.probe import human_needed
from llm_browser.repeat import ElementScope
from llm_browser.save_as import save_result
from llm_browser.selector_map import SelectorMap, resolve_step_refs, wall_signals
from llm_browser.selectors import ScopedSelector, parse_selector
from llm_browser.session import BrowserSession

logger = logging.getLogger(LOGGER_NAME)


def should_skip(session: BrowserSession, step: Step, data: FlowData) -> bool:
    """``element_missing`` is for idempotent toggles: click only when the post-click element is absent."""
    if not step.when:
        return False
    template_dict = data.to_template_dict()
    for raw_cond in step.when:
        if "element_exists" in raw_cond:
            spec = raw_cond["element_exists"]
            selector = parse_selector(spec["selector"])
            if not session.element_exists(selector):
                return True
        elif "element_missing" in raw_cond:
            spec = raw_cond["element_missing"]
            selector = parse_selector(spec["selector"])
            if session.element_exists(selector):
                return True
        elif "text_present" in raw_cond:
            spec = raw_cond["text_present"]
            scope = spec.get("selector")
            if not session.text_present(
                spec["text"],
                selector=parse_selector(scope) if scope is not None else None,
                exact=bool(spec.get("exact", False)),
            ):
                return True
        else:
            cond = compile_condition(raw_cond)
            value = template_dict.get(cond.field)
            if not evaluate_condition(cond.op, value, cond.param):
                return True
    return False


def resolve_step_templates(step: Step, data: FlowData) -> Step:
    """Idempotent; carries ``_parent`` so qualified names survive. A ``run-flow`` child body stays untemplated."""
    raw = step.model_dump(exclude_none=True)
    child_flow = raw.pop("flow", None)
    resolved_raw = resolve_templates_in_dict(raw, data.to_template_dict())
    if child_flow is not None:
        resolved_raw["flow"] = child_flow
    resolved = validate_step(resolved_raw)
    resolved._parent = step._parent
    return resolved


def resolve_step(
    step: Step,
    data: FlowData,
    selector_map: SelectorMap | None = None,
    scope: ElementScope | None = None,
) -> Step:
    resolved = resolve_step_templates(step, data)
    resolve_step_refs(resolved, selector_map)
    if resolved.scope is not None and scope is not None:
        # After the refs, so a `ref:` selector scopes like anything else.
        target = cast(Any, resolved)
        target.selector = ScopedSelector(
            root=scope.root, index=scope.index, inner=target.selector
        )
    return resolved


def page_needs_human(session: BrowserSession, selector_map: SelectorMap | None) -> bool:
    """Diagnostic only: a probe that fails must never replace the caller's error."""
    wall = wall_signals(selector_map)
    try:
        return human_needed(session.probe(wall=wall), wall)
    except Exception:
        logger.debug("probe failed while diagnosing a step failure", exc_info=True)
        return False


def execute_step(
    session: BrowserSession,
    step: Step,
    data: FlowData,
    behavior: Behavior | None = None,
    selector_map: SelectorMap | None = None,
    scope: ElementScope | None = None,
) -> ActionResult | FlowError:
    """``RunFlowStep`` never reaches here: ``run_loaded_flow`` dispatches it."""
    resolved = resolve_step(step, data, selector_map, scope)
    if should_skip(session, resolved, data):
        return SkippedResult(reason=WHEN_SKIP_REASON)
    # A save lands in the caller's ``data``: that is how later steps see it.
    action_result = save_result(
        resolved, execute_action(session, resolved, behavior), data
    )
    if not action_result.ok:
        capture = session.capture
        return FlowError(
            step=resolved.qualified_name,
            data=action_result,
            screenshot=(
                session.screenshot_bytes()
                if capture in ("screenshot", "both")
                else None
            ),
            dom=session.dom_snapshot() if capture in ("dom", "both") else None,
            human_needed=page_needs_human(session, selector_map),
            # A step that failed after its pick accepted a mismatch still ran
            # on that mismatch, so the run reports it.
            warnings=(
                []
                if action_result.accepted is None
                else [match_warning(resolved.qualified_name, action_result.accepted)]
            ),
        )
    if resolved.eval:
        session.evaluate(session.get_page(), resolved.eval)
    if resolved.wait_after:
        time.sleep(resolved.wait_after / 1000)
    return action_result
