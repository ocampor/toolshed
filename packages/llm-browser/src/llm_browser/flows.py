"""Stage two of the flow pipeline (a resolved document in, a validated ``Flow``
out) and stage three (run it). Neither stage touches the filesystem — every
``run-flow`` reference is inlined by :mod:`llm_browser.flow_pipeline` first."""

import re
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

from llm_browser.results import (
    ActionResult,
    BytesResult,
    ErrorResult,
    ParsedResult,
    SkippedResult,
    TextResult,
)
from llm_browser.constants import OUTPUT_ACTIONS, WHEN_SKIP_REASON
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
    top-to-bottom. ``redact`` scrubs every text the result carries — outputs,
    the error, and the failure DOM; binary payloads are left as they are."""
    secrets = clean_secrets(redact)
    with redacting_logs(secrets):
        result = run_loaded_flow(session, flow, data, from_step=from_step)
    if isinstance(result, FlowSuccess):
        return FlowSuccess(
            step=result.step,
            outputs=redact_secrets(result.outputs, secrets),
            skipped=redact_secrets(result.skipped, secrets),
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
    """``None`` for steps that produce nothing worth keeping (a click, a
    skipped step). Bytes come back as the :class:`BytesResult` itself, so the
    caller holds the real payload and not a base64 string."""
    if step.action not in OUTPUT_ACTIONS:
        return None
    match result:
        case ParsedResult():
            return [
                row.model_dump() if row is not None else None for row in result.rows
            ]
        case TextResult():
            return result.text
        case BytesResult():
            return result
        case _:
            return None


def indexed(name: str, index: int | None) -> str:
    """``name`` as one ``repeat`` pass keys it, so passes never collide."""
    return name if index is None else f"{name}[{index}]"


def unindexed(name: str) -> tuple[str, int | None]:
    """The inverse of :func:`indexed`: ``"shot[2]"`` is step ``shot``, pass 2.

    Whatever holds a step's own declaration — the CLI's ``path:`` table — keys
    it by the plain step name, so reading a pass's output back needs the name
    the pass was keyed from.
    """
    match = INDEXED_NAME.fullmatch(name)
    if match is None:
        return name, None
    return match["name"], int(match["index"])


INDEXED_NAME = re.compile(r"(?P<name>.*)\[(?P<index>\d+)\]")


def repeat_passes(step: Step, data: FlowData) -> Iterator[tuple[int | None, FlowData]]:
    """The data each pass of ``step`` runs against — one pass unless it repeats.

    Each item is bound under ``repeat.bind``, with its position under
    ``<bind>_index``, so a step can name either. A list nobody passed is no
    items rather than an error: an optional list param left out means the step
    has nothing to do. Anything else that is not a list is a data error.
    """
    if step.repeat is None:
        yield None, data
        return
    items = data.to_template_dict().get(step.repeat.over)
    if items is None:
        return
    if not isinstance(items, list):
        raise ValueError(
            f"step {step.name!r} repeats over {step.repeat.over!r}, which is "
            f"{type(items).__name__}, not a list"
        )
    for index, item in enumerate(items):
        yield (
            index,
            FlowData.model_validate(
                {
                    **data.model_dump(),
                    step.repeat.bind: item,
                    f"{step.repeat.bind}_index": index,
                }
            ),
        )


def repeat_data_error(
    step: Step,
    exc: ValueError,
    outputs: dict[str, object],
    skipped: list[SkippedStep],
) -> FlowError:
    """A ``repeat`` over something that is not a list fails like any other step.

    Raising instead would cost the caller the whole run: the steps before this
    one already ran, and their outputs only reach anyone through the result.
    """
    return FlowError(
        step=step.qualified_name,
        data=ErrorResult(
            error="ValueError", message=str(exc), step_name=step.qualified_name
        ),
        outputs=dict(outputs),
        skipped=list(skipped),
    )


def record_outcome(
    step: Step,
    outcome: ActionResult | FlowSuccess,
    index: int | None,
    outputs: dict[str, object],
    skipped: list[SkippedStep],
) -> None:
    """Fold one pass's result into the run's outputs and skip list."""
    match outcome:
        case FlowSuccess():
            outputs.update({indexed(k, index): v for k, v in outcome.outputs.items()})
            skipped.extend(
                s.model_copy(update={"name": indexed(s.name, index)})
                for s in outcome.skipped
            )
        case SkippedResult():
            skipped.append(
                SkippedStep(
                    name=indexed(step.qualified_name, index), reason=outcome.reason
                )
            )
        case _:
            output = step_output(step, outcome)
            if output is not None:
                outputs[indexed(step.qualified_name, index)] = output


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
    skipped: list[SkippedStep] = []
    for step in select_steps(flow.steps, from_step):
        try:
            passes = list(repeat_passes(step, flow_data))
        except ValueError as exc:
            return repeat_data_error(step, exc, outputs, skipped)
        for index, pass_data in passes:
            outcome: ActionResult | FlowSuccess | FlowError = (
                run_subflow(session, step, pass_data)
                if isinstance(step, RunFlowStep)
                else execute_step(session, step, pass_data)
            )
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


def run_subflow(
    session: BrowserSession,
    step: RunFlowStep,
    flow_data: FlowData,
) -> FlowSuccess | FlowError:
    """A skipped step comes back as an empty success; a swallowed
    ``optional:`` failure comes back as a success carrying the child's
    partial outputs, so the parent advances without losing that work. Either
    way the step is named in ``skipped``, child skips included."""
    resolved = resolve_step(step, flow_data)
    if not isinstance(resolved, RunFlowStep) or not isinstance(resolved.flow, SubFlow):
        raise RuntimeError(f"step {step.name!r} lost its sub-flow while templating")
    if should_skip(session, resolved, flow_data):
        return FlowSuccess(
            step=resolved.name,
            skipped=[
                SkippedStep(name=resolved.qualified_name, reason=WHEN_SKIP_REASON)
            ],
        )
    result = run_loaded_flow(session, resolved.flow, resolved.data)
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
