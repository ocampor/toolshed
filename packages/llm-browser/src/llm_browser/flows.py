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
)
from llm_browser.session import BrowserSession
from llm_browser.steps import execute_step, resolve_step, should_skip

SelectorMap = dict[str, dict[str, Any]]


def load_flow(
    flow_path: str | Path,
    *,
    selector_map: SelectorMap | None = None,
) -> Flow:
    """Load a flow YAML, resolve every ``run-flow`` reference, and
    expand selector-map ``ref:``s — all inside one
    ``Flow.model_validate`` call.

    The validation context carries:

    - ``base_dir`` so ``RunFlowStep``'s after-validator can read each
      referenced child YAML and attach it as ``step.subflow``.
    - ``selector_map`` so ``BaseStep``'s before-validator can replace
      ``ref: <key>`` with ``selector: <map[key]>`` before pydantic
      checks the model shape. Strict: an unknown ref raises a
      ``ValidationError`` at this point, not a "selector required"
      cascade later.

    Missing files, malformed YAML, sub-flow constraint violations,
    unknown refs — every load-time error surfaces from this call.
    """
    path = Path(flow_path).resolve()
    return Flow.model_validate(
        yaml.safe_load(path.read_text()),
        context={"base_dir": path.parent, "selector_map": selector_map},
    )


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
    layer and pass it through). When provided, refs in every step
    (including sub-flow children) are resolved during ``load_flow``.

    ``from_step`` re-enters the flow at the named step, skipping every
    step before it. Useful for retrying after a partial failure: read
    ``retry_hint.failed_step`` from the previous result, fix the
    issue, re-run with ``from_step=<failed step name>``. Step names
    are unique within a flow (enforced by ``Flow``'s validator), so
    the lookup is unambiguous. The flag does not propagate into
    sub-flows; children always run top-to-bottom.
    """
    flow = load_flow(str(Path(flow_path).resolve()), selector_map=selector_map)
    result = _run_flow(session, flow, data, from_step=from_step)
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
    from_step: str | None = None,
) -> FlowSuccess | FlowError:
    """Iterate ``flow.steps`` against ``session``. Sub-flow steps
    recurse back into ``_run_flow`` with their child Flow + step data;
    everything else goes through ``execute_step``. Leaf-only constraint
    on ``SubFlow`` bounds the recursion at depth one. Selector-map
    refs were already expanded during ``load_flow``, so steps reach
    here with their concrete ``selector:`` set.
    """
    flow_data = flow.validate_data(data)
    for step in _select_steps(flow.steps, from_step):
        match step:
            case RunFlowStep():
                resolved = resolve_step(step, flow_data)
                if not isinstance(resolved, RunFlowStep) or resolved.subflow is None:
                    raise RuntimeError(
                        f"RunFlowStep {resolved.name!r} has no `subflow` attached; "
                        "ensure the parent was loaded via `load_flow` rather "
                        "than constructed directly."
                    )
                if not should_skip(session, resolved, flow_data):
                    result = _run_flow(session, resolved.subflow, resolved.data)
                    if isinstance(result, FlowError) and not resolved.optional:
                        return result
            case _:
                error = execute_step(session, step, flow_data)
                if error is not None:
                    return error
    last_name = flow.steps[-1].name if flow.steps else "end"
    return FlowSuccess(step=last_name)
