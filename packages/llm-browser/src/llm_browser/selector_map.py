"""Selector map: load a YAML file mapping symbolic names to selectors, name the
refs a flow needs, and swap each one for its selector as a step runs."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any, NamedTuple

import yaml

from llm_browser.models import Flow, RunFlowStep, Step, SubFlow
from llm_browser.selectors import RefSelector, parse_selector

SelectorValue = str | dict[str, Any]
SelectorMap = dict[str, SelectorValue]


def load_selector_map(path: Path) -> SelectorMap:
    """Load a selector_map.yaml into a flat lookup: 'group.name' -> selector."""
    raw = yaml.safe_load(path.read_text())
    flat: SelectorMap = {}
    for group_name, fields in raw.items():
        for field_name, selector_spec in fields.items():
            flat[f"{group_name}.{field_name}"] = selector_spec
    return flat


class MissingSelectorsError(ValueError):
    """Every ref the map does not carry, named once, sorted."""

    def __init__(self, missing: list[str], available: list[str]) -> None:
        self.missing = missing
        self.available = available
        label = "selector ref" if len(missing) == 1 else "selector refs"
        names = ", ".join(repr(name) for name in missing)
        super().__init__(
            f"{label} {names} not found in selector_map; available: {available}"
        )


class RefSite(NamedTuple):
    """One model whose ``selector`` is a ref, and the name it asks for."""

    owner: Any
    ref: str


def step_ref_sites(step: Step) -> Iterator[RefSite]:
    """Every ref site one step owns — its own selector and its ``fields:`` /
    ``read:`` entries' — never an embedded sub-flow's: a child step resolves
    its own refs when it runs."""
    for owner in (step, *step.fields, *step.read.values()):
        selector = getattr(owner, "selector", None)
        if isinstance(selector, RefSelector):
            yield RefSite(owner, selector.ref)


def flow_ref_sites(flow: Flow) -> Iterator[RefSite]:
    for step in flow.steps:
        yield from step_ref_sites(step)
        if isinstance(step, RunFlowStep) and isinstance(step.flow, SubFlow):
            yield from flow_ref_sites(step.flow)


def selector_refs(flow: Flow) -> list[str]:
    """Every ref in a selector position — a step's own, its ``fields:`` and
    ``read:`` entries', sub-flows included — sorted and unique, which is what
    a host builds its map from. A ``ref:`` under a ``when:`` predicate is not
    such a position and is not named here."""
    return sorted({site.ref for site in flow_ref_sites(flow)})


def missing_selectors(flow: Flow, selector_map: SelectorMap) -> list[str]:
    """The refs the flow needs and the map lacks, sorted and unique."""
    return [ref for ref in selector_refs(flow) if ref not in selector_map]


def resolve_step_refs(step: Step, selector_map: SelectorMap | None) -> None:
    """Swap every ref in ``step`` for the map's selector, in place — the step
    is ``resolve_step``'s own fresh copy. Raises
    :class:`MissingSelectorsError` naming every ref the map lacks."""
    available = selector_map or {}
    sites = list(step_ref_sites(step))
    missing = sorted({site.ref for site in sites if site.ref not in available})
    if missing:
        raise MissingSelectorsError(missing, sorted(available))
    for site in sites:
        site.owner.selector = parse_selector(available[site.ref])
