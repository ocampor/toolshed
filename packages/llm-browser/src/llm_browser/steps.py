"""Step execution: resolve templates, evaluate conditions, dispatch actions."""

import time

from yaml_engine.compile import compile_condition
from yaml_engine.conditions import evaluate_condition
from yaml_engine.template import resolve_templates_in_dict

from llm_browser.actions import execute_action
from llm_browser.models import FlowData, FlowError, Step, validate_step
from llm_browser.selectors import parse_selector
from llm_browser.session import BrowserSession


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


def execute_step(
    session: BrowserSession,
    step: Step,
    data: FlowData,
) -> FlowError | None:
    """Execute a single action step.

    Returns a ``FlowError`` only when the action fails (``ok=False``) —
    that result carries the error data and a capture (screenshot / DOM)
    to help the caller diagnose. Returns ``None`` on success so the
    caller can advance to the next step.

    Sub-flow composition (``RunFlowStep``) is the runner's concern, not
    this function's; ``run_flow`` / ``_run_flow`` dispatches those before
    delegating here.
    """
    resolved = resolve_step(step, data)
    if should_skip(session, resolved, data):
        return None
    action_result = execute_action(session, resolved)
    if not action_result.ok:
        screenshot_path = (
            str(session.take_screenshot())
            if session.capture in ("screenshot", "both")
            else None
        )
        dom_path = (
            str(session.take_dom_snapshot())
            if session.capture in ("dom", "both")
            else None
        )
        return FlowError(
            step=resolved.qualified_name,
            data=action_result,
            screenshot=screenshot_path,
            dom=dom_path,
        )
    if resolved.eval:
        session.driver.evaluate(session.get_page(), resolved.eval)
    if resolved.wait_after:
        time.sleep(resolved.wait_after / 1000)
    return None
