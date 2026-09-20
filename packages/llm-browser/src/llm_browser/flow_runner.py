"""Stage three of the flow pipeline: run a validated ``Flow``, step by step.

:mod:`llm_browser.flows` is the surface callers use; this module is the loop
underneath it — one step's passes at a time, sub-flows included.
"""

from typing import NamedTuple

from yaml_engine.template import TemplatePathError

from llm_browser.behavior import Behavior
from llm_browser.constants import WHEN_SKIP_REASON
from llm_browser.flow_passes import (
    Pass,
    RunState,
    child_data,
    indexed,
    record_outcome,
    repeat_data_error,
    repeat_passes,
)
from llm_browser.iterations import IterationReport, failed_pass
from llm_browser.models import (
    Flow,
    FlowData,
    FlowError,
    FlowSuccess,
    RunFlowStep,
    SkippedStep,
    Step,
    SubFlow,
)
from llm_browser.repeat import ElementScope, OnError
from llm_browser.results import ActionResult
from llm_browser.selector_map import SelectorMap
from llm_browser.session import BrowserSession
from llm_browser.steps import execute_step, resolve_step, should_skip


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


class RunContext(NamedTuple):
    session: BrowserSession
    behavior: Behavior | None = None
    selector_map: SelectorMap | None = None
    only: dict[str, list[int]] | None = None
    scope: ElementScope | None = None


def run_loaded_flow(
    session: BrowserSession,
    flow: Flow,
    data: dict[str, object],
    *,
    from_step: str | None = None,
    behavior: Behavior | None = None,
    selector_map: SelectorMap | None = None,
    only: dict[str, list[int]] | None = None,
    scope: ElementScope | None = None,
) -> FlowSuccess | FlowError:
    """``SubFlow``'s leaf-only constraint bounds the recursion at depth one.
    ``behavior`` defaults every step of this flow and its sub-flows; ``scope``
    is the element the enclosing pass confined them to."""
    flow_data = flow.validate_data(data)
    state = RunState()
    context = RunContext(session, behavior, selector_map, only, scope)
    for step in select_steps(flow.steps, from_step):
        failure = run_step(step, flow_data, state, context)
        if failure is not None:
            return failure
    last_name = flow.steps[-1].name if flow.steps else "end"
    return FlowSuccess(
        step=last_name,
        outputs=state.outputs,
        skipped=state.skipped,
        warnings=state.warnings,
        iterations=state.iterations,
    )


def run_step(
    step: Step, flow_data: FlowData, state: RunState, context: RunContext
) -> FlowError | None:
    """Run every pass of one step; ``None`` when the flow goes on."""
    try:
        passes = repeat_passes(
            context.session, step, flow_data, context.selector_map, context.only
        )
    except ValueError as exc:
        return repeat_data_error(step, exc, state)
    report = start_report(step, len(passes), state)
    for position, one in enumerate(passes):
        outcome = run_pass(step, one, context)
        if isinstance(outcome, FlowError):
            record_failure(one, outcome, report, context)
            if step.repeat is None or step.repeat.on_error is OnError.stop:
                record_unrun(passes[position + 1 :], report)
                return stopped_at(outcome, one.index, state)
            outcome = folded_failure(
                step.qualified_name, outcome, f"pass failed at {outcome.step}"
            )
        elif report is not None:
            report.ok += 1
        record_outcome(step, outcome, one.index, state)
    return None


def record_failure(
    one: Pass,
    failure: FlowError,
    report: IterationReport | None,
    context: RunContext,
) -> None:
    """One failed pass, in full. A step that does not repeat has no report."""
    if report is None:
        return
    report.failed.append(
        failed_pass(
            one.index or 0,
            one.item,
            indexed(failure.step, one.index),
            failure.data,
            page_url(context.session),
            failure.screenshot,
        )
    )


def record_unrun(passes: list[Pass], report: IterationReport | None) -> None:
    """The passes a stopped loop left behind, in the order they would have run
    — already narrowed by ``only``, since that is what built ``passes``."""
    if report is not None:
        report.not_run = [one.index for one in passes if one.index is not None]


def run_pass(
    step: Step, one: Pass, context: RunContext
) -> ActionResult | FlowSuccess | FlowError:
    scope = one.scope if one.scope is not None else context.scope
    try:
        if isinstance(step, RunFlowStep):
            return run_subflow(
                context.session,
                step,
                one.data,
                context.behavior,
                context.selector_map,
                scope,
                context.only,
            )
        return execute_step(
            context.session,
            step,
            one.data,
            context.behavior,
            context.selector_map,
            scope,
        )
    except TemplatePathError as exc:
        # This pass's own failure: the run's outputs are the caller's to merge.
        return repeat_data_error(step, exc, RunState())


def start_report(step: Step, total: int, state: RunState) -> IterationReport | None:
    """A repeating step reports its passes even when there were none."""
    if step.repeat is None:
        return None
    report = IterationReport(total=total, over=step.repeat.param)
    state.iterations[step.qualified_name] = report
    return report


def stopped_at(failure: FlowError, index: int | None, state: RunState) -> FlowError:
    """A sub-flow failure already carries the child's outputs; keep both
    sides, qualified names keep the keys distinct, and the pass's index keys
    them exactly as a success would."""
    return failure.model_copy(
        update={
            "step": indexed(failure.step, index),
            "outputs": {
                **state.outputs,
                **{indexed(k, index): v for k, v in failure.outputs.items()},
            },
            "skipped": [
                *state.skipped,
                *(
                    s.model_copy(update={"name": indexed(s.name, index)})
                    for s in failure.skipped
                ),
            ],
            "warnings": [
                *state.warnings,
                *(
                    w.model_copy(update={"step": indexed(w.step, index)})
                    for w in failure.warnings
                ),
            ],
            "iterations": {
                **state.iterations,
                **{indexed(k, index): v for k, v in failure.iterations.items()},
            },
        }
    )


def folded_failure(name: str, failure: FlowError, reason: str) -> FlowSuccess:
    """A failure kept as partial work: whatever it collected stays in
    ``outputs`` and the step is named in ``skipped`` with what went wrong."""
    return FlowSuccess(
        step=name,
        outputs=failure.outputs,
        skipped=[*failure.skipped, SkippedStep(name=name, reason=reason)],
        warnings=failure.warnings,
        iterations=failure.iterations,
    )


def page_url(session: BrowserSession) -> str:
    """Diagnostic only: a url a failing page will not give up must never
    replace the failure the caller came for."""
    try:
        return session.current_url()
    except Exception:
        return ""


def run_subflow(
    session: BrowserSession,
    step: RunFlowStep,
    flow_data: FlowData,
    behavior: Behavior | None = None,
    selector_map: SelectorMap | None = None,
    scope: ElementScope | None = None,
    only: dict[str, list[int]] | None = None,
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
        only=only,
        scope=scope,
    )
    if isinstance(result, FlowError) and resolved.optional:
        return folded_failure(
            resolved.qualified_name, result, f"sub-flow failed at {result.step}"
        )
    return result
