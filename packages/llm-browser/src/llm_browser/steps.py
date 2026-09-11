"""Step execution: resolve templates, evaluate conditions, dispatch actions."""

import logging
import time

from yaml_engine.compile import compile_condition
from yaml_engine.conditions import evaluate_condition
from yaml_engine.template import resolve_templates_in_dict

from llm_browser.actions import execute_action
from llm_browser.captcha import CaptchaSolver
from llm_browser.results import ActionResult, ErrorResult, SkippedResult
from llm_browser.constants import LOGGER_NAME
from llm_browser.models import (
    FlowData,
    FlowError,
    SolveCaptchaStep,
    Step,
    validate_step,
)
from llm_browser.probe import human_needed
from llm_browser.selectors import parse_selector
from llm_browser.session import BrowserSession

logger = logging.getLogger(LOGGER_NAME)


def should_skip(session: BrowserSession, step: Step, data: FlowData) -> bool:
    """Return True if the step's when clause is not satisfied.

    Supported predicates:
      * ``element_exists``  — skip unless the element is present.
      * ``element_missing`` — skip unless the element is absent
        (idempotent toggles: only click when the post-click element
        isn't already there).
      * Plain field/op/value forms compiled by ``yaml_engine``.
    """
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
        else:
            cond = compile_condition(raw_cond)
            value = template_dict.get(cond.field)
            if not evaluate_condition(cond.op, value, cond.param):
                return True
    return False


def resolve_step(step: Step, data: FlowData) -> Step:
    """Resolve {{ template }} refs inside ``step`` against ``data`` and
    return a freshly-validated Step. Idempotent — resolving a resolved
    step is a no-op. Carries ``_parent`` (a private attr set during
    flow load) across the round trip so qualified names survive."""
    raw = step.model_dump(exclude_none=True)
    resolved = validate_step(resolve_templates_in_dict(raw, data.to_template_dict()))
    resolved._parent = step._parent
    return resolved


def page_needs_human(session: BrowserSession) -> bool:
    """Whether the failing page is asking for a login or a challenge.

    Diagnostic only: a probe that itself fails must never replace the error
    the caller actually cares about.
    """
    try:
        return human_needed(session.probe())
    except Exception:
        logger.debug("probe failed while diagnosing a step failure", exc_info=True)
        return False


def execute_step(
    session: BrowserSession,
    step: Step,
    data: FlowData,
    *,
    solver: CaptchaSolver | None = None,
) -> ActionResult | FlowError:
    """A ``when:``-skipped step returns a ``SkippedResult``, not a failure.
    ``RunFlowStep`` never reaches here — ``run_loaded_flow`` dispatches it."""
    resolved = resolve_step(step, data)
    if isinstance(resolved, SolveCaptchaStep):
        resolved._solver = solver
    if should_skip(session, resolved, data):
        return SkippedResult(reason="when condition not satisfied")
    action_result = execute_action(session, resolved)
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
            human_needed=page_needs_human(session)
            or (isinstance(action_result, ErrorResult) and action_result.human_needed),
        )
    if resolved.eval:
        session.evaluate(session.get_page(), resolved.eval)
    if resolved.wait_after:
        time.sleep(resolved.wait_after / 1000)
    return action_result
