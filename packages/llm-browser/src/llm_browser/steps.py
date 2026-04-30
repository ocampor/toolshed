"""Step execution: resolve templates, evaluate conditions, dispatch actions."""

import time
from typing import Callable

from yaml_engine.compile import compile_condition
from yaml_engine.conditions import evaluate_condition
from yaml_engine.template import resolve_templates_in_dict

from llm_browser.actions import execute_action
from llm_browser.models import FlowData, FlowResult, RunFlowStep, Step, validate_step
from llm_browser.selectors import parse_selector
from llm_browser.session import BrowserSession

SubflowDispatcher = Callable[[RunFlowStep], "FlowResult | None"]


def should_skip(session: BrowserSession, step: Step, data: FlowData) -> bool:
    """Return True if the step's when clause is not satisfied."""
    if not step.when:
        return False
    template_dict = data.to_template_dict()
    for raw_cond in step.when:
        if "element_exists" in raw_cond:
            spec = raw_cond["element_exists"]
            selector = parse_selector(spec["selector"])
            if not session.element_exists(selector):
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
    step is a no-op."""
    raw = step.model_dump(exclude_none=True)
    return validate_step(resolve_templates_in_dict(raw, data.to_template_dict()))


def execute_step(
    session: BrowserSession,
    step: Step,
    data: FlowData,
    *,
    subflow: SubflowDispatcher | None = None,
) -> FlowResult | None:
    """Execute a single flow step of any kind.

    Returns a ``FlowResult`` to halt the caller — at a checkpoint (success)
    or when the action returns ``ok=False`` (error short-circuit). Returns
    ``None`` to continue to the next step.

    For ``run-flow`` steps the caller must pass ``subflow`` — a callback
    that takes the resolved ``RunFlowStep`` and runs the referenced flow
    (``FlowRunner`` provides this binding). Callers that don't compose
    sub-flows can omit it; it's only required when a ``RunFlowStep``
    actually appears in the input.
    """
    resolved = resolve_step(step, data)
    if should_skip(session, resolved, data):
        return None
    if isinstance(resolved, RunFlowStep):
        if subflow is None:
            raise RuntimeError(
                "execute_step received a RunFlowStep but no `subflow` "
                "dispatcher was provided. Use FlowRunner.run() so it can "
                "bind one, or pass `subflow=...` explicitly."
            )
        return subflow(resolved)
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
        return FlowResult(
            step=resolved.name,
            data=action_result,
            screenshot=screenshot_path,
            dom=dom_path,
        )
    if resolved.eval:
        eval_result = session.driver.evaluate(session.get_page(), resolved.eval)
    else:
        eval_result = None
    if resolved.wait_after:
        time.sleep(resolved.wait_after / 1000)
    if not resolved.checkpoint:
        return None
    result_data = eval_result if eval_result is not None else action_result
    screenshot_path = (
        str(session.take_screenshot())
        if session.capture in ("screenshot", "both")
        else None
    )
    dom_path = (
        str(session.take_dom_snapshot()) if session.capture in ("dom", "both") else None
    )
    return FlowResult(
        step=resolved.name,
        data=result_data,
        screenshot=screenshot_path,
        dom=dom_path,
    )
