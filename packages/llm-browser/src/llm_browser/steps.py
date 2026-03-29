"""Step execution: resolve templates, evaluate conditions, dispatch actions."""

import time

from yaml_engine.compile import compile_condition
from yaml_engine.conditions import evaluate_condition
from yaml_engine.template import resolve_templates_in_dict

from llm_browser.actions import execute_action
from llm_browser.fields import execute_field
from llm_browser.models import FlowData, FlowResult, Step
from llm_browser.session import BrowserSession

from playwright.sync_api import Page


def should_skip(step: Step, data: FlowData) -> bool:
    """Return True if the step's when clause is not satisfied."""
    if not step.when:
        return False
    template_dict = data.to_template_dict()
    for raw_cond in step.when:
        cond = compile_condition(raw_cond)
        value = template_dict.get(cond.field)
        if not evaluate_condition(cond.op, value, cond.param):
            return True
    return False


def dispatch_action(page: Page, step: Step) -> None:
    """Dispatch step action to registered handler."""
    execute_action(page, step)


def dispatch_fields(page: Page, step: Step) -> None:
    """Execute all field handlers for the step."""
    for field_def in step.fields:
        execute_field(page, field_def)


def dispatch_eval(page: Page, step: Step) -> object | None:
    """Run JavaScript eval if present in the step."""
    if step.eval:
        return page.evaluate(step.eval)
    return None


def apply_wait(step: Step) -> None:
    """Sleep for wait_after milliseconds if specified."""
    if step.wait_after:
        time.sleep(step.wait_after / 1000)


def maybe_checkpoint(
    session: BrowserSession,
    step: Step,
    eval_result: object | None,
) -> FlowResult | None:
    """Return a FlowResult with screenshot if checkpoint is set."""
    if not step.checkpoint:
        return None
    screenshot_path = session.take_screenshot()
    return FlowResult(
        step=step.name,
        data=eval_result,
        screenshot=str(screenshot_path),
    )


def execute_step(
    session: BrowserSession,
    step: Step,
    data: FlowData,
) -> FlowResult | None:
    """Execute a single flow step. Returns FlowResult at checkpoint, else None."""
    raw = step.model_dump(exclude_none=True)
    template_dict = data.to_template_dict()
    resolved_dict = resolve_templates_in_dict(raw, template_dict)
    resolved = Step.model_validate(resolved_dict)
    if should_skip(resolved, data):
        return None
    page = session.get_page()
    dispatch_action(page, resolved)
    dispatch_fields(page, resolved)
    eval_result = dispatch_eval(page, resolved)
    apply_wait(resolved)
    return maybe_checkpoint(session, resolved, eval_result)
