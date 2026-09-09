"""Parse YAML flow text and execute the steps end-to-end."""

from collections.abc import Callable, Iterable
from typing import Any

import yaml

from llm_browser.actions import ActionResult, ParsedResult, TextResult
from llm_browser.constants import OUTPUT_ACTIONS
from llm_browser.models import (
    Flow,
    FlowData,
    FlowError,
    FlowResult,
    FlowSuccess,
    RetryHint,
    RunFlowStep,
    Step,
)
from llm_browser.redact import clean_secrets, redacting_logs, redact_secrets
from llm_browser.session import BrowserSession
from llm_browser.steps import execute_step, resolve_step, should_skip

SelectorMap = dict[str, dict[str, Any]]

#: Maps a ``run-flow`` reference to the sub-flow's YAML text.
SubflowLoader = Callable[[str], str]


def load_flow_text(
    text: str,
    *,
    subflow_loader: SubflowLoader | None = None,
    selector_map: SelectorMap | None = None,
) -> Flow:
    """``run-flow`` refs resolve eagerly: an existing file is read from disk,
    anything else goes to ``subflow_loader`` (``ValueError`` without one)."""
    return Flow.model_validate(
        yaml.safe_load(text),
        context={"subflow_loader": subflow_loader, "selector_map": selector_map},
    )


def run_flow(
    session: BrowserSession,
    flow: Flow,
    data: dict[str, object],
    *,
    from_step: str | None = None,
    redact: Iterable[str] = (),
) -> FlowResult:
    """``from_step`` does not propagate into sub-flows; children always run
    top-to-bottom. ``redact`` leaves files written by ``path:`` steps alone."""
    secrets = clean_secrets(redact)
    with redacting_logs(secrets):
        result = run_loaded_flow(session, flow, data, from_step=from_step)
    if isinstance(result, FlowSuccess):
        return FlowSuccess(
            step=result.step,
            outputs=redact_secrets(result.outputs, secrets),
        )
    # `result.step` is qualified; its first segment is the top-level step
    # name, which is what ``--from`` operates on.
    return FlowError(
        step=result.step,
        data=redact_secrets(result.data, secrets),
        screenshot=result.screenshot,
        dom=result.dom,
        human_needed=result.human_needed,
        retry_hint=RetryHint(
            data=redact_secrets(data, secrets),
            failed_step=result.step.split("/", 1)[0],
            error=redact_secrets(str(result.data), secrets),
        ),
    )


def select_steps(steps: list[Step], from_step: str | None) -> list[Step]:
    if from_step is None:
        return steps
    try:
        start = next(i for i, s in enumerate(steps) if s.name == from_step)
    except StopIteration:
        raise ValueError(
            f"step {from_step!r} not found in flow; "
            f"available: {[s.name for s in steps]}"
        )
    return steps[start:]


def step_output(step: Step, result: ActionResult) -> object | None:
    """``None`` for steps whose result isn't kept in memory (screenshots stay
    paths on disk)."""
    if step.action not in OUTPUT_ACTIONS:
        return None
    match result:
        case ParsedResult():
            return [
                row.model_dump() if row is not None else None for row in result.rows
            ]
        case TextResult():
            return result.text
        case _:
            return None


def run_loaded_flow(
    session: BrowserSession,
    flow: Flow,
    data: dict[str, object],
    *,
    from_step: str | None = None,
) -> FlowSuccess | FlowError:
    """``SubFlow``'s leaf-only constraint bounds the recursion at depth one."""
    flow_data = flow.validate_data(data)
    outputs: dict[str, object] = {}
    for step in select_steps(flow.steps, from_step):
        outcome: ActionResult | FlowSuccess | FlowError = (
            run_subflow(session, step, flow_data)
            if isinstance(step, RunFlowStep)
            else execute_step(session, step, flow_data)
        )
        match outcome:
            case FlowError():
                return outcome
            case FlowSuccess():
                outputs.update(outcome.outputs)
            case _:
                output = step_output(step, outcome)
                if output is not None:
                    outputs[step.qualified_name] = output
    last_name = flow.steps[-1].name if flow.steps else "end"
    return FlowSuccess(step=last_name, outputs=outputs)


def run_subflow(
    session: BrowserSession,
    step: RunFlowStep,
    flow_data: FlowData,
) -> FlowSuccess | FlowError:
    """A skipped step and a swallowed ``optional:`` failure both come back as
    an empty success, so the parent advances."""
    resolved = resolve_step(step, flow_data)
    if not isinstance(resolved, RunFlowStep) or resolved.subflow is None:
        raise RuntimeError(
            f"RunFlowStep {resolved.name!r} has no `subflow` attached; "
            "load the parent with `load_flow_text` or `load_flow`"
        )
    if should_skip(session, resolved, flow_data):
        return FlowSuccess(step=resolved.name)
    result = run_loaded_flow(session, resolved.subflow, resolved.data)
    if isinstance(result, FlowError) and resolved.optional:
        return FlowSuccess(step=resolved.name)
    return result
