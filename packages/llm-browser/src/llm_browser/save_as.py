"""``save_as``: a read's rows become flow data for the steps after it."""

from collections.abc import Iterable

from yaml_engine.template import template_names

from llm_browser.flow_passes import step_output
from llm_browser.models import (
    Flow,
    FlowData,
    ReadStep,
    RunFlowStep,
    SaveAs,
    Step,
    SubFlow,
)
from llm_browser.params import resolve_params
from llm_browser.results import ActionResult, ErrorResult, ParsedResult


def saved_value(save_as: SaveAs, rows: list[object]) -> object:
    if save_as.field is None:
        return rows
    row = next((row for row in rows if row_matches(row, save_as.where)), None)
    value = row.get(save_as.field) if isinstance(row, dict) else None
    if value is None:
        raise ValueError(
            f"save_as {save_as.name!r}: none of {len(rows)} rows has "
            f"{save_as.field!r}"
            + (f" where {save_as.where!r}" if save_as.where else "")
        )
    return value


def row_matches(row: object, where: dict[str, object]) -> bool:
    if not where:
        return True
    return isinstance(row, dict) and all(row.get(k) == v for k, v in where.items())


def save_result(step: Step, result: ActionResult, data: FlowData) -> ActionResult:
    """Bind ``result``'s rows into ``data``; a scalar no row yields fails the step."""
    if not isinstance(step, ReadStep) or step.save_as is None:
        return result
    if not isinstance(result, ParsedResult):
        return result
    rows = step_output(step, result)
    assert isinstance(rows, list)
    try:
        value = saved_value(step.save_as, rows)
    except ValueError as exc:
        return ErrorResult(
            error="ValueError", message=str(exc), step_name=step.qualified_name
        )
    setattr(data, step.save_as.name, value)
    return result


def save_names(steps: Iterable[Step]) -> list[str]:
    return [
        step.save_as.name
        for step in steps
        if isinstance(step, ReadStep) and step.save_as is not None
    ]


def names_used(step: Step) -> set[str]:
    """Every flow-data name ``step`` reads, its sub-flow's steps included."""
    used = template_names(step.model_dump(exclude_none=True))
    used |= {str(cond["field"]) for cond in step.when if "field" in cond}
    if step.repeat is not None:
        used.add(step.repeat.over)
    if isinstance(step, RunFlowStep) and isinstance(step.flow, SubFlow):
        for child in step.flow.steps:
            used |= names_used(child)
    return used


def names_bound(step: RunFlowStep) -> set[str]:
    bound = set(step.data)
    if step.repeat is not None:
        bound |= {step.repeat.bind, f"{step.repeat.bind}_index"}
    return bound


def reject_shadowing(saves: list[str], taken: set[str], where: str) -> None:
    seen = set(taken)
    for name in saves:
        if name in seen:
            raise ValueError(
                f"save_as {name!r}{where} shadows a param or another save_as"
            )
        seen.add(name)


def check_saved_names(flow: Flow) -> None:
    saves = save_names(flow.steps)
    taken = set(resolve_params(flow.params))
    reject_shadowing(saves, taken, "")
    for step in flow.steps:
        if isinstance(step, RunFlowStep) and isinstance(step.flow, SubFlow):
            reject_shadowing(
                save_names(step.flow.steps),
                taken | set(saves) | names_bound(step),
                f" in sub-flow {step.name!r}",
            )
    pending = set(saves)
    for step in flow.steps:
        early = sorted(names_used(step) & pending)
        if early:
            raise ValueError(
                f"step {step.name!r} uses {early!r} before the step that saves it"
            )
        pending -= set(save_names([step]))
