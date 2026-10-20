"""Selector map: load a YAML file mapping symbolic names to selectors, name the
refs a flow needs, and swap each one for its selector as a step runs.

A flow writes ``ref: <group>.<name>`` where a selector would go — or the long
``selector: {ref: ...}`` — and never carries the selector itself, so a site
that moves its markup is one map edit rather than a flow edit. The map is a
two-level YAML file, ``group: {name: selector}``, given to the CLI as
``--selector-map`` or to :func:`llm_browser.flows.run_flow` as
``selector_map=``. Refs resolve per step, at run time: a ref the map lacks
fails the load, not the step, so a typo never reaches a browser.

The ``wall`` group is not for refs: each entry adds a sign that a failing
step's page needs a human, on top of the built-in ones. A CSS entry (plain
string or ``{css: ...}``) counts as a challenge element; a ``text=...`` entry
is a substring of the page's body text, compared case- and accent-blind, so
write a full sentence rather than a word every page says. Any other kind
fails the load.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any, NamedTuple

import yaml

from llm_browser.constants import ENGINE_PREFIX_PATTERN, WALL_GROUP
from llm_browser.models import Flow, RunFlowStep, Step, SubFlow, WallSignals
from llm_browser.selectors import RefSelector, Selector, parse_selector

SelectorValue = str | dict[str, Any]
SelectorMap = dict[str, SelectorValue]


def load_selector_map(path: Path) -> SelectorMap:
    """Load a selector_map.yaml into a flat lookup: 'group.name' -> selector."""
    raw = yaml.safe_load(path.read_text())
    flat: SelectorMap = {}
    for group_name, fields in raw.items():
        for field_name, selector_spec in fields.items():
            flat[f"{group_name}.{field_name}"] = selector_spec
    wall_signals(flat)  # result unused: a bad wall entry fails here, not mid-flow
    return flat


def wall_signals(selector_map: SelectorMap | None) -> WallSignals:
    """The map's ``wall.*`` entries; any kind but CSS or ``text=`` raises."""
    selectors: list[str] = []
    phrases: list[str] = []
    for name, spec in (selector_map or {}).items():
        if name.partition(".")[0] != WALL_GROUP:
            continue
        match spec:
            case str() if spec.startswith("text="):
                phrases.append(require_phrase(name, spec.removeprefix("text=")))
            case str() if ENGINE_PREFIX_PATTERN.match(spec) is None:
                selectors.append(require_css(name, spec))
            case {"css": str(css)}:
                selectors.append(require_css(name, css))
            case _:
                raise ValueError(
                    f"selector_map entry {name!r}: a wall entry is CSS or text=..., "
                    f"got {spec!r}"
                )
    return WallSignals(selectors=tuple(selectors), phrases=tuple(phrases))


def require_phrase(name: str, phrase: str) -> str:
    """An empty phrase is a substring of every page."""
    if not phrase.strip():
        raise ValueError(f"selector_map entry {name!r}: empty text= phrase")
    return phrase


def require_css(name: str, css: str) -> str:
    """Catches what ``:is()`` cannot forgive: empty or unbalanced brackets."""
    if not css.strip() or not has_balanced_brackets(css):
        raise ValueError(f"selector_map entry {name!r}: unparsable CSS {css!r}")
    return css


def has_balanced_brackets(css: str) -> bool:
    # debt: a bracket inside a quoted attribute value counts too.
    openers = {")": "(", "]": "["}
    stack: list[str] = []
    for char in css:
        if char in "([":
            stack.append(char)
        elif char in openers and (not stack or stack.pop() != openers[char]):
            return False
    return not stack


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
    """One model whose ``field`` holds a ref, and the name it asks for."""

    owner: Any
    ref: str
    field: str = "selector"


def step_ref_sites(step: Step) -> Iterator[RefSite]:
    """Every ref site one step owns — its own selector, its ``fields:`` /
    ``read:`` entries' and its ``repeat: { over_selector: }`` — never an
    embedded sub-flow's: a child step resolves its own refs when it runs."""
    for owner in (step, *step.fields, *step.read.values()):
        selector = getattr(owner, "selector", None)
        if isinstance(selector, RefSelector):
            yield RefSite(owner, selector.ref)
    if step.repeat is not None and isinstance(step.repeat.over_selector, RefSelector):
        yield RefSite(step.repeat, step.repeat.over_selector.ref, "over_selector")


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
        setattr(site.owner, site.field, parse_selector(available[site.ref]))


def resolve_ref(selector: Selector, selector_map: SelectorMap | None) -> Selector:
    if not isinstance(selector, RefSelector):
        return selector
    available = selector_map or {}
    if selector.ref not in available:
        raise MissingSelectorsError([selector.ref], sorted(available))
    return parse_selector(available[selector.ref])
