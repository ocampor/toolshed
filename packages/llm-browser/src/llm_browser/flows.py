"""Load YAML flows and execute their steps end-to-end."""

from pathlib import Path
from typing import Any

import yaml

from llm_browser.models import (
    Flow,
    FlowError,
    FlowResult,
    FlowSuccess,
    RetryHint,
    RunFlowStep,
    Step,
    SubFlow,
    validate_step,
)
from llm_browser.selector_map import resolve_refs
from llm_browser.session import BrowserSession
from llm_browser.steps import execute_step, resolve_step, should_skip

SelectorMap = dict[str, dict[str, Any]]


def load_flow(flow_path: str | Path) -> Flow:
    """Load a flow YAML and resolve every ``run-flow`` reference.

    Reads the parent file, then validates with
    ``context={"base_dir": <parent dir>}`` — ``RunFlowStep``'s after-
    validator uses that context to read each referenced child YAML
    and attach it as ``step.subflow``. Missing files, malformed YAML,
    and sub-flow constraint violations all surface from this call.
    """
    path = Path(flow_path).resolve()
    return Flow.model_validate(
        yaml.safe_load(path.read_text()),
        context={"base_dir": path.parent},
    )


def resolve_step_refs(step: Step, selector_map: SelectorMap) -> Step:
    """Resolve selector-map references in a step, returning a new Step."""
    raw = step.model_dump(exclude_none=True)
    resolved = resolve_refs(raw, selector_map)
    return validate_step(resolved)


def run_flow(
    session: BrowserSession,
    flow_path: str | Path,
    data: dict[str, object],
    *,
    selector_map: SelectorMap | None = None,
    from_step: str | None = None,
) -> FlowResult:
    """Run a YAML flow against ``session`` to completion (or to the
    first failing step).

    ``selector_map`` is the loaded selector-map dict (call
    :func:`llm_browser.selector_map.load_selector_map` once at the CLI
    layer and pass it through). When provided, every step's selector
    refs are resolved before execution.

    ``from_step`` re-enters the flow at the named step, skipping every
    step before it. Useful for retrying after a partial failure: read
    ``last_failure.json``, fix the issue, re-run with
    ``from_step=<failed step name>``. Step names are unique within a
    flow (enforced by ``Flow``'s validator), so the lookup is
    unambiguous. The flag does not propagate into sub-flows; children
    always run top-to-bottom.
    """
    flow = load_flow(str(Path(flow_path).resolve()))
    result = _run_flow(
        session, flow, data, selector_map=selector_map, from_step=from_step
    )
    if isinstance(result, FlowError):
        # `result.step` is a slash-separated qualified name (set in
        # execute_step from the failing step's ``qualified_name``);
        # the first segment is the parent flow's top-level step name,
        # which is what ``--from`` operates on.
        return FlowError(
            step=result.step,
            data=result.data,
            screenshot=result.screenshot,
            dom=result.dom,
            retry_hint=RetryHint(
                flow_path=str(flow_path),
                data=data,
                failed_step=result.step.split("/", 1)[0],
                error=str(result.data),
            ),
        )
    return result


def _select_steps(steps: list[Step], from_step: str | None) -> list[Step]:
    """Return the steps to execute. With ``from_step``, slice from
    the named step onward; raise ``ValueError`` if the name isn't in
    ``steps``."""
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


def _run_flow(
    session: BrowserSession,
    flow: Flow,
    data: dict[str, object],
    *,
    selector_map: SelectorMap | None = None,
    from_step: str | None = None,
) -> FlowSuccess | FlowError:
    """Iterate ``flow.steps`` against ``session``. Sub-flow steps
    recurse back into ``_run_flow`` with their child Flow + step data;
    everything else goes through ``execute_step``. Leaf-only constraint
    on ``SubFlow`` bounds the recursion at depth one.
    """
    flow_data = flow.validate_data(data)
    for step in _select_steps(flow.steps, from_step):
        prepared = resolve_step_refs(step, selector_map) if selector_map else step
        match prepared:
            case RunFlowStep():
                resolved = resolve_step(prepared, flow_data)
                if not isinstance(resolved, RunFlowStep) or resolved.subflow is None:
                    raise RuntimeError(
                        f"RunFlowStep {resolved.name!r} has no `subflow` attached; "
                        "ensure the parent was loaded via `load_flow` rather "
                        "than constructed directly."
                    )
                if not should_skip(session, resolved, flow_data):
                    result = _run_flow(
                        session,
                        resolved.subflow,
                        resolved.data,
                        selector_map=selector_map,
                    )
                    if isinstance(result, FlowError) and not resolved.optional:
                        return result
            case _:
                error = execute_step(session, prepared, flow_data)
                if error is not None:
                    return error
    last_name = flow.steps[-1].name if flow.steps else "end"
    return FlowSuccess(step=last_name)
