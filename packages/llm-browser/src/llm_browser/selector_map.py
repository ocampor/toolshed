"""Selector map: load a YAML file mapping symbolic names to selectors, collect
the refs a flow document needs, and expand them."""

import copy
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any, NamedTuple

import yaml

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


# A ``run-flow`` step's ``data:`` is flow arguments, not selectors: a child
# param that happens to be called ``ref`` is a literal value.
LITERAL_KEYS = frozenset({"data"})


def is_ref(key: str, value: Any) -> bool:
    """A ``{ref: name}`` mapping standing in for a selector."""
    return key not in LITERAL_KEYS and isinstance(value, dict) and set(value) == {"ref"}


class RefSite(NamedTuple):
    """One place a document names a selector by ref, and how to fill it in."""

    ref: str
    apply: Callable[[SelectorValue], None]


def write_at(target: dict[str, Any], key: str) -> Callable[[SelectorValue], None]:
    def apply(spec: SelectorValue) -> None:
        target[key] = spec

    return apply


def write_selector(target: dict[str, Any]) -> Callable[[SelectorValue], None]:
    def apply(spec: SelectorValue) -> None:
        target.pop("ref")
        target["selector"] = spec

    return apply


def write_field_selector(field: dict[str, Any]) -> Callable[[SelectorValue], None]:
    """A field takes a mapping carrying ``id`` as its own ``id``, ignoring that
    mapping's other keys; anything else, a string included, lands under
    ``selector``."""

    def apply(spec: SelectorValue) -> None:
        field.pop("ref")
        if isinstance(spec, dict) and "id" in spec:
            field["id"] = spec["id"]
        else:
            field["selector"] = spec

    return apply


def step_ref_sites(step: dict[str, Any]) -> Iterator[RefSite]:
    """Every ref one step names, never an embedded ``flow:``'s — that is
    :func:`document_ref_sites`' business. Step-level ``ref:`` is yielded after
    the selector-valued keys so it wins on a step carrying both."""
    for key, value in step.items():
        if is_ref(key, value):
            yield RefSite(str(value["ref"]), write_at(step, key))
    if "ref" in step and not isinstance(step["ref"], dict):
        yield RefSite(str(step["ref"]), write_selector(step))
    fields = step.get("fields")
    if isinstance(fields, list):
        for field in fields:
            if isinstance(field, dict) and "ref" in field:
                yield RefSite(str(field["ref"]), write_field_selector(field))
    read = step.get("read")
    if isinstance(read, dict):
        for spec in read.values():
            if isinstance(spec, dict) and "ref" in spec:
                yield RefSite(str(spec["ref"]), write_selector(spec))


def document_ref_sites(document: dict[str, Any]) -> Iterator[RefSite]:
    steps = document.get("steps")
    if not isinstance(steps, list):
        return
    for step in steps:
        if not isinstance(step, dict):
            continue
        yield from step_ref_sites(step)
        child = step.get("flow")
        if isinstance(child, dict):
            yield from document_ref_sites(child)


def selector_refs(document: Mapping[str, Any]) -> list[str]:
    """Every ref the document needs, sub-flows included, sorted and unique —
    what a host builds its map from before expanding."""
    return sorted({site.ref for site in document_ref_sites(dict(document))})


def fill_sites(sites: list[RefSite], selector_map: SelectorMap) -> None:
    missing = sorted({site.ref for site in sites if site.ref not in selector_map})
    if missing:
        raise MissingSelectorsError(missing, sorted(selector_map))
    for site in sites:
        site.apply(selector_map[site.ref])


def expand_selector_refs(
    document: Mapping[str, Any], selector_map: SelectorMap
) -> dict[str, Any]:
    """Replace every ``ref:`` in the document — the parent's steps and any
    embedded sub-flow's — with its selector. Raises
    :class:`MissingSelectorsError` naming every ref the map lacks."""
    expanded = copy.deepcopy(dict(document))
    fill_sites(list(document_ref_sites(expanded)), selector_map)
    return expanded


def resolve_refs(
    step_dict: dict[str, Any],
    selector_map: SelectorMap,
) -> dict[str, Any]:
    """One step's refs expanded, the same way :func:`expand_selector_refs`
    expands a whole document's."""
    resolved = copy.deepcopy(dict(step_dict))
    fill_sites(list(step_ref_sites(resolved)), selector_map)
    return resolved
