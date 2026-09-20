"""One pass of a step: the data it runs against, the keys it writes under.

A step without ``repeat`` is a single pass with no index, so the runner folds
every outcome the same way and only these functions know an index exists.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from llm_browser.constants import OUTPUT_ACTIONS
from llm_browser.iterations import IterationReport
from llm_browser.models import (
    FlowData,
    FlowError,
    FlowSuccess,
    SkippedStep,
    Step,
)
from llm_browser.parse import parse_extract_spec
from llm_browser.repeat import ElementScope
from llm_browser.results import (
    ActionResult,
    BytesResult,
    ErrorResult,
    ParsedResult,
    SkippedResult,
    TextResult,
)
from llm_browser.selector_map import SelectorMap, resolve_ref
from llm_browser.selectors import PlainSelector, RefSelector, ScopedSelector
from llm_browser.session import BrowserSession


@dataclass
class RunState:
    outputs: dict[str, object] = field(default_factory=dict)
    skipped: list[SkippedStep] = field(default_factory=list)
    iterations: dict[str, IterationReport] = field(default_factory=dict)


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


@dataclass(frozen=True)
class Pass:
    index: int | None
    data: FlowData
    item: object = None
    scope: ElementScope | None = None


def repeat_passes(
    session: BrowserSession,
    step: Step,
    data: FlowData,
    selector_map: SelectorMap | None = None,
    only: dict[str, list[int]] | None = None,
) -> list[Pass]:
    """Every pass of ``step`` — one pass unless it repeats.

    Each item is bound under ``repeat.bind``, with its position under
    ``<bind>_index``, so a step can name either. ``only`` keeps just the passes
    whose index it names for this step; the indices are the original ones.
    """
    repeat = step.repeat
    if repeat is None:
        return [Pass(None, data)]
    items, root = repeat_source(session, step, data, selector_map)
    wanted = None if only is None else only.get(step.qualified_name)
    passes = []
    for index, item in enumerate(items):
        if wanted is not None and index not in wanted:
            continue
        bound = {**data.model_dump(), repeat.bind: item, f"{repeat.bind}_index": index}
        passes.append(
            Pass(
                index,
                FlowData.model_validate(bound),
                item,
                None if root is None else ElementScope(root, index),
            )
        )
    return passes


def repeat_source(
    session: BrowserSession,
    step: Step,
    data: FlowData,
    selector_map: SelectorMap | None,
) -> tuple[list[object], PlainSelector | None]:
    """What this step repeats over, and the element root when it has one.

    A list nobody passed is no items rather than an error: an optional list
    param left out means the step has nothing to do. Anything else that is not
    a list is a data error.
    """
    repeat = step.repeat
    assert repeat is not None
    if repeat.over_selector is not None:
        root = resolve_ref(repeat.over_selector, selector_map)
        if isinstance(root, (RefSelector, ScopedSelector)):
            raise ValueError(f"repeat over_selector {root!r} names no element")
        # Counted once, and no handle is kept: a pass re-resolves the root and
        # its index when it addresses the element, binding this much of its text.
        rows = session.parse_elements(root, parse_extract_spec(None))
        return [" ".join((row.get("text") or "").split())[:80] for row in rows], root
    if isinstance(repeat.over, list):
        return list(repeat.over), None
    items = data.to_template_dict().get(str(repeat.over))
    if items is None:
        return [], None
    if not isinstance(items, list):
        raise ValueError(
            f"step {step.name!r} repeats over {repeat.over!r}, which is "
            f"{type(items).__name__}, not a list"
        )
    return items, None


def repeat_data_error(step: Step, exc: ValueError, state: RunState) -> FlowError:
    """Flow data a step cannot run on — a ``repeat`` over a non-list, a dotted
    template path to nothing — fails like any other step.

    Raising instead would cost the caller the whole run: the steps before this
    one already ran, and their outputs only reach anyone through the result.
    """
    return FlowError(
        step=step.qualified_name,
        data=ErrorResult(
            error="ValueError", message=str(exc), step_name=step.qualified_name
        ),
        outputs=dict(state.outputs),
        skipped=list(state.skipped),
        iterations=dict(state.iterations),
    )


def record_outcome(
    step: Step,
    outcome: ActionResult | FlowSuccess,
    index: int | None,
    state: RunState,
) -> None:
    """Fold one pass's result into the run's outputs, skips and reports."""
    match outcome:
        case FlowSuccess():
            state.outputs.update(
                {indexed(k, index): v for k, v in outcome.outputs.items()}
            )
            state.skipped.extend(
                s.model_copy(update={"name": indexed(s.name, index)})
                for s in outcome.skipped
            )
            state.iterations.update(
                {indexed(k, index): v for k, v in outcome.iterations.items()}
            )
        case SkippedResult():
            state.skipped.append(
                SkippedStep(
                    name=indexed(step.qualified_name, index), reason=outcome.reason
                )
            )
        case _:
            output = step_output(step, outcome)
            if output is not None:
                state.outputs[indexed(step.qualified_name, index)] = output


def child_data(parent: FlowData, bindings: dict[str, Any]) -> dict[str, object]:
    """A parent param the step does not bind stays visible to the child; one it
    binds is overridden, so ``data: { x: "{{ y }}" }`` reaches the child as the
    bound value even when the parent has its own ``x``."""
    return {**parent.to_template_dict(), **bindings}
