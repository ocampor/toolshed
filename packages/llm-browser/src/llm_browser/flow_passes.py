"""One pass of a step: the data it runs against, the keys it writes under.

A step without ``repeat`` is a single pass with no index, so the runner folds
every outcome the same way and only these functions know an index exists.
"""

import re
from collections.abc import Iterator

from llm_browser.constants import OUTPUT_ACTIONS
from llm_browser.models import (
    FlowData,
    FlowError,
    FlowSuccess,
    SkippedStep,
    Step,
)
from llm_browser.results import (
    ActionResult,
    BytesResult,
    ErrorResult,
    ParsedResult,
    SkippedResult,
    TextResult,
)


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
