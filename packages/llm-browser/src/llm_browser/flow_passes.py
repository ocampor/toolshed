"""Only these functions know an index exists; a step without ``repeat`` is one unindexed pass."""

import re
from dataclasses import dataclass, field
from typing import Any

from llm_browser.constants import OUTPUT_ACTIONS
from llm_browser.iterations import IterationReport
from llm_browser.models import (
    FlowData,
    FlowError,
    FlowSuccess,
    MatchWarning,
    SkippedStep,
    Step,
    match_warning,
)
from llm_browser.parse import parse_extract_spec
from llm_browser.repeat import ElementScope
from llm_browser.results import (
    ActionResult,
    BytesResult,
    DocumentResult,
    ErrorResult,
    ExtractError,
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
    warnings: list[MatchWarning] = field(default_factory=list)
    extract_errors: list[ExtractError] = field(default_factory=list)


def step_output(step: Step, result: ActionResult) -> object | None:
    """Bytes come back as the :class:`BytesResult` itself, not a base64 string."""
    if step.action not in OUTPUT_ACTIONS:
        return None
    match result:
        case ParsedResult():
            return [
                row.model_dump() if row is not None else None for row in result.rows
            ]
        case TextResult():
            return result.text
        case BytesResult() | DocumentResult():
            return result
        case _:
            return None


def indexed(name: str, index: int | None) -> str:
    return name if index is None else f"{name}[{index}]"


def unindexed(name: str) -> tuple[str, int | None]:
    """The CLI's ``path:`` table keys by the plain step name."""
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
    """Items bind under ``repeat.bind`` and positions under ``<bind>_index``; ``only`` keeps original indices."""
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
    """An absent list param is no items, not an error; any other non-list is a data error."""
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
    """Fails like any step, not a raise: earlier steps' outputs only reach the caller through the result."""
    return FlowError(
        step=step.qualified_name,
        data=ErrorResult(
            error="ValueError", message=str(exc), step_name=step.qualified_name
        ),
        outputs=dict(state.outputs),
        skipped=list(state.skipped),
        warnings=list(state.warnings),
        extract_errors=list(state.extract_errors),
        iterations=dict(state.iterations),
    )


def record_outcome(
    step: Step,
    outcome: ActionResult | FlowSuccess,
    index: int | None,
    state: RunState,
) -> None:
    if isinstance(outcome, ActionResult) and outcome.accepted is not None:
        state.warnings.append(
            match_warning(indexed(step.qualified_name, index), outcome.accepted)
        )
    if isinstance(outcome, ParsedResult):
        state.extract_errors.extend(
            stepped(w, indexed(step.qualified_name, index))
            for w in outcome.extract_errors
        )
    match outcome:
        case FlowSuccess():
            state.outputs.update(
                {indexed(k, index): v for k, v in outcome.outputs.items()}
            )
            state.skipped.extend(
                s.model_copy(update={"name": indexed(s.name, index)})
                for s in outcome.skipped
            )
            state.warnings.extend(
                w.model_copy(update={"step": indexed(w.step, index)})
                for w in outcome.warnings
            )
            state.extract_errors.extend(
                stepped(w, indexed(w.step, index)) for w in outcome.extract_errors
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


def stepped(warning: ExtractError, step: str) -> ExtractError:
    return warning.model_copy(update={"step": step})


def child_data(parent: FlowData, bindings: dict[str, Any]) -> dict[str, object]:
    """A parent param the step binds is overridden for the child; one it does not stays visible."""
    return {**parent.to_template_dict(), **bindings}
