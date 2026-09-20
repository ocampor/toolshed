"""Stage two of the flow pipeline (a resolved document in, a validated ``Flow``
out) and stage three (run it). Neither stage touches the filesystem — every
``run-flow`` reference is inlined by :mod:`llm_browser.flow_pipeline` first."""

from collections.abc import Iterable, Mapping
from typing import Any

from yaml_engine.template import TemplatePathError

from llm_browser.behavior import Behavior, profile
from llm_browser.results import ActionResult
from llm_browser.constants import WHEN_SKIP_REASON
from llm_browser.flow_passes import (
    indexed,
    record_outcome,
    repeat_data_error,
    repeat_passes,
    unindexed,
)
from llm_browser.flow_pipeline import parse_flow_yaml
from llm_browser.models import (
    Flow,
    FlowData,
    FlowError,
    FlowResult,
    FlowSuccess,
    RetryHint,
    RunFlowStep,
    SkippedStep,
    Step,
    SubFlow,
)
from llm_browser.redact import clean_secrets, redacting_logs, redact_secrets
from llm_browser.selector_map import SelectorMap
from llm_browser.session import BrowserSession
from llm_browser.steps import execute_step, resolve_step, should_skip


def load_flow_text(text: str) -> Flow:
    return load_flow_document(parse_flow_yaml(text))


def load_flow_document(document: Mapping[str, Any]) -> Flow:
    return Flow.model_validate(document)


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
    behavior: Behavior | None = None,
    selector_map: SelectorMap | None = None,
) -> FlowResult:
    """``from_step`` does not propagate into sub-flows; children always run
    top-to-bottom. ``redact`` scrubs every text the result carries — outputs,
    the error, and the failure DOM; binary payloads are left as they are.

    ``behavior`` is this run's humanization default: every step takes it
    unless it sets its own ``humanize``. It is carried down to each step
    rather than written onto the session, so the session a caller passed in
    comes back out of the run exactly as it went in.

    ``selector_map`` supplies every ``ref:`` selector the flow names, its
    sub-flows' included, as each step runs; check with
    :func:`~llm_browser.selector_map.missing_selectors` first, because a ref
    the map lacks raises
    :class:`~llm_browser.selector_map.MissingSelectorsError` mid-run."""
    secrets = clean_secrets(redact)
    with redacting_logs(secrets):
        result = run_loaded_flow(
            session,
            flow,
            data,
            from_step=from_step,
            behavior=behavior,
            selector_map=selector_map,
        )
    ran_as = profile(behavior if behavior is not None else session.behavior)
    if isinstance(result, FlowSuccess):
        return FlowSuccess(
            step=result.step,
            outputs=redact_secrets(result.outputs, secrets),
            skipped=redact_secrets(result.skipped, secrets),
            behavior=ran_as,
        )
    # `result.step` is qualified and names the failing `repeat` pass; the
    # first segment without its index is the top-level step name, which is
    # what ``--from`` operates on — a pass cannot be resumed on its own.
    return FlowError(
        step=result.step,
        data=redact_secrets(result.data, secrets),
        outputs=redact_secrets(result.outputs, secrets),
        skipped=redact_secrets(result.skipped, secrets),
        screenshot=result.screenshot,
        dom=redact_secrets(result.dom, secrets),
        human_needed=result.human_needed,
        retry_hint=RetryHint(
            data=redact_secrets(data, secrets),
            failed_step=unindexed(result.step.split("/", 1)[0])[0],
            error=redact_secrets(str(result.data), secrets),
        ),
        behavior=ran_as,
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


def run_loaded_flow(
    session: BrowserSession,
    flow: Flow,
    data: dict[str, object],
    *,
    from_step: str | None = None,
    behavior: Behavior | None = None,
    selector_map: SelectorMap | None = None,
) -> FlowSuccess | FlowError:
    """``SubFlow``'s leaf-only constraint bounds the recursion at depth one.
    ``behavior`` defaults every step of this flow and its sub-flows."""
    flow_data = flow.validate_data(data)
    outputs: dict[str, object] = {}
    skipped: list[SkippedStep] = []
    for step in select_steps(flow.steps, from_step):
        try:
            passes = list(repeat_passes(step, flow_data))
        except ValueError as exc:
            return repeat_data_error(step, exc, outputs, skipped)
        for index, pass_data in passes:
            outcome = run_pass(session, step, pass_data, behavior, selector_map)
            if isinstance(outcome, FlowError):
                # A sub-flow failure already carries the child's outputs;
                # keep both sides, qualified names keep the keys distinct, and
                # the pass's index keys them exactly as a success would.
                return outcome.model_copy(
                    update={
                        "step": indexed(outcome.step, index),
                        "outputs": {
                            **outputs,
                            **{
                                indexed(k, index): v for k, v in outcome.outputs.items()
                            },
                        },
                        "skipped": [
                            *skipped,
                            *(
                                s.model_copy(update={"name": indexed(s.name, index)})
                                for s in outcome.skipped
                            ),
                        ],
                    }
                )
            record_outcome(step, outcome, index, outputs, skipped)
    last_name = flow.steps[-1].name if flow.steps else "end"
    return FlowSuccess(step=last_name, outputs=outputs, skipped=skipped)


def run_pass(
    session: BrowserSession,
    step: Step,
    pass_data: FlowData,
    behavior: Behavior | None,
    selector_map: SelectorMap | None,
) -> ActionResult | FlowSuccess | FlowError:
    try:
        if isinstance(step, RunFlowStep):
            return run_subflow(session, step, pass_data, behavior, selector_map)
        return execute_step(session, step, pass_data, behavior, selector_map)
    except TemplatePathError as exc:
        return repeat_data_error(step, exc, {}, [])


def run_subflow(
    session: BrowserSession,
    step: RunFlowStep,
    flow_data: FlowData,
    behavior: Behavior | None = None,
    selector_map: SelectorMap | None = None,
) -> FlowSuccess | FlowError:
    """A skipped step comes back as an empty success; a swallowed
    ``optional:`` failure comes back as a success carrying the child's
    partial outputs, so the parent advances without losing that work. Either
    way the step is named in ``skipped``, child skips included."""
    resolved = resolve_step(step, flow_data, selector_map)
    if not isinstance(resolved, RunFlowStep) or not isinstance(resolved.flow, SubFlow):
        raise RuntimeError(f"step {step.name!r} lost its sub-flow while templating")
    if should_skip(session, resolved, flow_data):
        return FlowSuccess(
            step=resolved.name,
            skipped=[
                SkippedStep(name=resolved.qualified_name, reason=WHEN_SKIP_REASON)
            ],
        )
    result = run_loaded_flow(
        session,
        resolved.flow,
        child_data(flow_data, resolved.data),
        behavior=behavior,
        selector_map=selector_map,
    )
    if isinstance(result, FlowError) and resolved.optional:
        return FlowSuccess(
            step=resolved.name,
            outputs=result.outputs,
            skipped=[
                *result.skipped,
                SkippedStep(
                    name=resolved.qualified_name,
                    reason=f"sub-flow failed at {result.step}",
                ),
            ],
        )
    return result


def child_data(parent: FlowData, bindings: dict[str, Any]) -> dict[str, object]:
    """A parent param the step does not bind stays visible to the child; one it
    binds is overridden, so ``data: { x: "{{ y }}" }`` reaches the child as the
    bound value even when the parent has its own ``x``."""
    return {**parent.to_template_dict(), **bindings}
