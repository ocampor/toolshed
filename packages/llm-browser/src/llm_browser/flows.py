"""Stage two of the flow pipeline (a resolved document in, a validated ``Flow``
out) and stage three (run it). Neither stage touches the filesystem — every
``run-flow`` reference is inlined by :mod:`llm_browser.flow_pipeline` first."""

from collections.abc import Iterable, Mapping
from typing import Any

from llm_browser.actions import ActionResult, ParsedResult, TextResult
from llm_browser.constants import OUTPUT_ACTIONS
from llm_browser.flow_pipeline import parse_flow_yaml
from llm_browser.models import (
    Flow,
    FlowData,
    FlowError,
    FlowResult,
    FlowSuccess,
    RetryHint,
    RunFlowStep,
    Step,
    SubFlow,
)
from llm_browser.redact import clean_secrets, redacting_logs, redact_secrets
from llm_browser.selector_map import SelectorMap, resolve_refs
from llm_browser.session import BrowserSession
from llm_browser.steps import execute_step, resolve_step, should_skip


def load_flow_text(text: str) -> Flow:
    return load_flow_document(parse_flow_yaml(text))


def load_flow_document(
    document: Mapping[str, Any],
    *,
    selector_map: SelectorMap | None = None,
) -> Flow:
    """``selector_map`` expands every ``ref:`` in the document — the parent's
    steps and any embedded sub-flow's — before validation."""
    if selector_map is not None:
        document = expand_selector_refs(document, selector_map)
    return Flow.model_validate(document)


def expand_selector_refs(
    document: Mapping[str, Any], selector_map: SelectorMap
) -> dict[str, Any]:
    steps = document.get("steps")
    if not isinstance(steps, list):
        return dict(document)
    expanded = [expand_step_selector_refs(step, selector_map) for step in steps]
    return {**document, "steps": expanded}


def expand_step_selector_refs(step: Any, selector_map: SelectorMap) -> Any:
    if not isinstance(step, dict):
        return step
    resolved = resolve_refs(step, selector_map)
    child = resolved.get("flow")
    if isinstance(child, Mapping):
        resolved["flow"] = expand_selector_refs(child, selector_map)
    return resolved


def with_flow_path(result: FlowResult, flow_path: str) -> FlowResult:
    """Fill ``retry_hint.flow_path`` for a flow that came from a file."""
    if not isinstance(result, FlowError) or result.retry_hint is None:
        return result
    hint = result.retry_hint.model_copy(update={"flow_path": flow_path})
    return result.model_copy(update={"retry_hint": hint})


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
        outputs=redact_secrets(result.outputs, secrets),
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
                # A sub-flow failure already carries the child's outputs;
                # keep both sides, qualified names keep the keys distinct.
                return outcome.model_copy(
                    update={"outputs": {**outputs, **outcome.outputs}}
                )
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
    """A skipped step comes back as an empty success; a swallowed
    ``optional:`` failure comes back as a success carrying the child's
    partial outputs, so the parent advances without losing that work."""
    resolved = resolve_step(step, flow_data)
    if not isinstance(resolved, RunFlowStep) or not isinstance(resolved.flow, SubFlow):
        raise RuntimeError(f"step {step.name!r} lost its sub-flow while templating")
    if should_skip(session, resolved, flow_data):
        return FlowSuccess(step=resolved.name)
    result = run_loaded_flow(session, resolved.flow, resolved.data)
    if isinstance(result, FlowError) and resolved.optional:
        return FlowSuccess(step=resolved.name, outputs=result.outputs)
    return result
