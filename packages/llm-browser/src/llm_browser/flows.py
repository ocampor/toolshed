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

#: Maps a ``run-flow`` step's ``flow:`` reference to the sub-flow's YAML
#: text. Lets a caller compose flows that never touch disk.
SubflowLoader = Callable[[str], str]


def load_flow_text(
    text: str,
    *,
    subflow_loader: SubflowLoader | None = None,
    selector_map: SelectorMap | None = None,
) -> Flow:
    """Load a flow from YAML text — the no-filesystem twin of
    :func:`llm_browser.flow_files.load_flow`.

    ``run-flow`` steps still resolve eagerly: a ``flow:`` reference that
    names an existing file is read from disk (so a text flow can reuse
    on-disk children), and anything else is handed to ``subflow_loader``,
    which returns the child's YAML text. Children stay leaf-only, exactly
    as with :func:`llm_browser.flow_files.load_flow`.

    Raises ``ValueError`` when a reference resolves to neither a file nor
    a loader.
    """
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
    """Run an already-loaded flow against ``session`` to completion (or
    to the first failing step).

    ``flow`` is a :class:`Flow` model — build one with
    :func:`load_flow_text`, or with
    :func:`llm_browser.flow_files.load_flow` to read it from disk. To
    run a flow file in one call, use
    :func:`llm_browser.flow_files.run_flow_file`, which also fills in
    ``RetryHint.flow_path``; this runner leaves it empty.

    ``from_step`` re-enters the flow at the named step, skipping every
    step before it. Useful for retrying after a partial failure: read
    ``retry_hint.failed_step`` from the previous result, fix the
    issue, re-run with ``from_step=<failed step name>``. Step names
    are unique within a flow (enforced by ``Flow``'s validator), so
    the lookup is unambiguous. The flag does not propagate into
    sub-flows; children always run top-to-bottom.

    ``redact`` lists secret values injected through ``data``. Each is
    replaced by ``***`` in the retry hint, the error payload, the
    step outputs, and every ``llm_browser`` log record emitted while the
    flow runs. Files written by ``path:`` steps are not rewritten.
    """
    secrets = clean_secrets(redact)
    with redacting_logs(secrets):
        result = run_loaded_flow(session, flow, data, from_step=from_step)
    if isinstance(result, FlowSuccess):
        return FlowSuccess(
            step=result.step,
            outputs=redact_secrets(result.outputs, secrets),
        )
    # `result.step` is a slash-separated qualified name (set in
    # execute_step from the failing step's ``qualified_name``);
    # the first segment is the parent flow's top-level step name,
    # which is what ``--from`` operates on.
    return FlowError(
        step=result.step,
        data=redact_secrets(result.data, secrets),
        screenshot=result.screenshot,
        dom=result.dom,
        retry_hint=RetryHint(
            data=redact_secrets(data, secrets),
            failed_step=result.step.split("/", 1)[0],
            error=redact_secrets(str(result.data), secrets),
        ),
    )


def select_steps(steps: list[Step], from_step: str | None) -> list[Step]:
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


def step_output(step: Step, result: ActionResult) -> object | None:
    """Return what a data step produced, or ``None`` for steps whose
    result isn't worth keeping in memory (screenshots stay paths)."""
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
    """Iterate ``flow.steps`` against ``session``. Sub-flow steps
    recurse back into ``run_loaded_flow`` with their child Flow + step
    data; everything else goes through ``execute_step``. Leaf-only
    constraint on ``SubFlow`` bounds the recursion at depth one.
    Selector-map refs were already expanded at load time, so
    steps reach here with their concrete ``selector:`` set.

    Data-step results accumulate into ``FlowSuccess.outputs``, keyed by
    qualified step name; a child flow's outputs merge into the parent's
    under their ``<run-flow step>/<step>`` keys.
    """
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
    """Run a ``run-flow`` step's attached child flow. A skipped step and
    a swallowed failure on an ``optional:`` step both come back as an
    empty success so the parent advances."""
    resolved = resolve_step(step, flow_data)
    if not isinstance(resolved, RunFlowStep) or resolved.subflow is None:
        raise RuntimeError(
            f"RunFlowStep {resolved.name!r} has no `subflow` attached; "
            "ensure the parent was loaded via `load_flow_text` / `load_flow` "
            "rather than constructed directly."
        )
    if should_skip(session, resolved, flow_data):
        return FlowSuccess(step=resolved.name)
    result = run_loaded_flow(session, resolved.subflow, resolved.data)
    if isinstance(result, FlowError) and resolved.optional:
        return FlowSuccess(step=resolved.name)
    return result
