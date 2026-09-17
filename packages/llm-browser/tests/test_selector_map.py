"""Tests for selector map loading, ref collection, and ref expansion."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from llm_browser.selector_map import (
    MissingSelectorsError,
    expand_selector_refs,
    load_selector_map,
    resolve_refs,
    selector_refs,
)


def _write_map(tmp_path: Path) -> Path:
    path = tmp_path / "selector_map.yaml"
    path.write_text(
        yaml.dump(
            {
                "invoice": {
                    "rfc": {"id": "135textboxautocomplete55"},
                    "cp": {"id": "135textbox61"},
                },
                "declaracion": {
                    "copropiedad": {"id": "457select7"},
                },
            }
        )
    )
    return path


def test_load_selector_map(tmp_path: Path) -> None:
    path = _write_map(tmp_path)
    flat = load_selector_map(path)
    assert flat["invoice.rfc"] == {"id": "135textboxautocomplete55"}
    assert flat["invoice.cp"] == {"id": "135textbox61"}
    assert flat["declaracion.copropiedad"] == {"id": "457select7"}


def test_resolve_refs_step_level() -> None:
    selector_map = {"invoice.rfc": {"id": "135textboxautocomplete55"}}
    step = {"name": "fill_rfc", "ref": "invoice.rfc", "action": "click"}
    result = resolve_refs(step, selector_map)
    assert result["selector"] == {"id": "135textboxautocomplete55"}
    assert "ref" not in result


def test_resolve_refs_field_level() -> None:
    selector_map = {"invoice.rfc": {"id": "135textboxautocomplete55"}}
    step = {
        "name": "fill",
        "fields": [{"type": "text", "ref": "invoice.rfc", "value": "XEXX"}],
    }
    result = resolve_refs(step, selector_map)
    assert result["fields"][0]["id"] == "135textboxautocomplete55"
    assert "ref" not in result["fields"][0]


def test_resolve_refs_read_level() -> None:
    selector_map = {"invoice.cp": {"id": "135textbox61"}}
    step = {
        "name": "read",
        "action": "read_values",
        "read": {"cp": {"ref": "invoice.cp", "attribute": "value"}},
    }
    result = resolve_refs(step, selector_map)
    assert result["read"]["cp"]["selector"] == {"id": "135textbox61"}
    assert "ref" not in result["read"]["cp"]


def test_resolve_refs_no_ref_unchanged() -> None:
    step = {"name": "click", "action": "click", "selector": "#btn"}
    result = resolve_refs(step, {})
    assert result == step


def test_resolve_refs_unknown_ref_raises() -> None:
    """An unknown ref is a load-time error, not a silent no-op — caught
    here instead of cascading into a 'selector required' validation
    failure later."""
    step = {"name": "s", "ref": "unknown.ref"}
    with pytest.raises(ValueError, match="selector ref 'unknown.ref' not found"):
        resolve_refs(step, {})


def test_resolve_refs_expands_every_selector_valued_key() -> None:
    """A `ref:` standing in for a selector is expanded wherever it appears,
    not only under the top-level `selector` key."""
    selector_map = {
        "login.user": {"id": "userField"},
        "login.pass": {"css": "#answer"},
    }
    step = {
        "name": "s",
        "image": {"ref": "login.user"},
        "input": {"ref": "login.pass"},
        "submit": "#go",
    }
    result = resolve_refs(step, selector_map)
    assert result["image"] == {"id": "userField"}
    assert result["input"] == {"css": "#answer"}
    assert result["submit"] == "#go"


def test_resolve_refs_leaves_a_mapping_that_is_not_a_ref_alone() -> None:
    step = {"name": "s", "selector": {"css": "#a"}, "data": {"ref": "x", "n": 1}}
    assert resolve_refs(step, {}) == step


def test_resolve_refs_leaves_a_sub_flow_s_data_alone() -> None:
    """A `run-flow` child's `data:` is arguments, not selectors: a param that
    happens to be called `ref` keeps its literal value."""
    step = {
        "name": "child",
        "action": "run-flow",
        "flow": "child.yaml",
        "data": {"ref": "INV-1"},
    }
    assert resolve_refs(step, {}) == step


# --- collect: selector_refs ---

DOCUMENT: dict[str, Any] = {
    "steps": [
        {"name": "a", "action": "click", "ref": "ui.button"},
        {"name": "b", "image": {"ref": "ui.logo"}},
        {"name": "c", "fields": [{"type": "text", "ref": "form.rfc"}]},
        {"name": "d", "read": {"cp": {"ref": "form.cp", "attribute": "value"}}},
        {
            "name": "child",
            "action": "run-flow",
            "flow": {"steps": [{"name": "e", "ref": "child.ok"}]},
            "data": {"ref": "INV-1"},
        },
        {"name": "dup", "action": "click", "ref": "ui.button"},
    ]
}
DOCUMENT_REFS = ["child.ok", "form.cp", "form.rfc", "ui.button", "ui.logo"]

FULL_MAP: dict[str, Any] = {ref: {"id": ref} for ref in DOCUMENT_REFS}


def test_selector_refs_lists_every_ref_once_sorted() -> None:
    """Sub-flow refs included; a `run-flow` `data:` value is not a ref."""
    assert selector_refs(DOCUMENT) == DOCUMENT_REFS


def test_selector_refs_of_a_document_without_steps() -> None:
    assert selector_refs({"params": ["x"]}) == []


# --- expand: parity with collect ---


def test_a_map_of_exactly_the_collected_refs_expands() -> None:
    expanded = expand_selector_refs(DOCUMENT, FULL_MAP)
    assert selector_refs(expanded) == []
    assert expanded["steps"][0]["selector"] == {"id": "ui.button"}
    assert expanded["steps"][1]["image"] == {"id": "ui.logo"}
    assert expanded["steps"][2]["fields"][0]["id"] == "form.rfc"
    assert expanded["steps"][3]["read"]["cp"]["selector"] == {"id": "form.cp"}
    assert expanded["steps"][4]["flow"]["steps"][0]["selector"] == {"id": "child.ok"}
    assert expanded["steps"][4]["data"] == {"ref": "INV-1"}


@pytest.mark.parametrize("dropped", DOCUMENT_REFS)
def test_dropping_any_collected_ref_fails_naming_it(dropped: str) -> None:
    partial = {ref: spec for ref, spec in FULL_MAP.items() if ref != dropped}
    with pytest.raises(MissingSelectorsError) as excinfo:
        expand_selector_refs(DOCUMENT, partial)
    assert excinfo.value.missing == [dropped]
    assert dropped in str(excinfo.value)


def test_expansion_leaves_the_input_document_alone() -> None:
    expand_selector_refs(DOCUMENT, FULL_MAP)
    assert selector_refs(DOCUMENT) == DOCUMENT_REFS


def test_every_missing_ref_is_listed_at_once() -> None:
    with pytest.raises(MissingSelectorsError) as excinfo:
        expand_selector_refs(DOCUMENT, {"ui.button": {"id": "b"}})
    assert excinfo.value.missing == ["child.ok", "form.cp", "form.rfc", "ui.logo"]
    assert excinfo.value.available == ["ui.button"]


# --- expand: a string map value ---


@pytest.mark.parametrize(
    ("step", "read_selector"),
    [
        ({"name": "s", "action": "click", "ref": "ui.x"}, lambda s: s["selector"]),
        ({"name": "s", "image": {"ref": "ui.x"}}, lambda s: s["image"]),
        (
            {"name": "s", "fields": [{"ref": "ui.x"}]},
            lambda s: s["fields"][0]["selector"],
        ),
        (
            {"name": "s", "read": {"k": {"ref": "ui.x"}}},
            lambda s: s["read"]["k"]["selector"],
        ),
    ],
)
def test_a_string_selector_lands_under_selector_at_every_level(
    step: dict[str, Any], read_selector: Any
) -> None:
    """`text=Aside` must not be indexed like a map — the `id` branch is for
    mappings only."""
    resolved = resolve_refs(step, {"ui.x": "text=Aside"})
    assert read_selector(resolved) == "text=Aside"


# --- expand: a step carrying both a step-level and a key-level ref ---


@pytest.mark.parametrize(
    "step",
    [
        {"name": "s", "ref": "ui.a", "selector": {"ref": "ui.b"}},
        {"name": "s", "selector": {"ref": "ui.b"}, "ref": "ui.a"},
    ],
)
def test_a_step_level_ref_wins_over_a_selector_key_ref(step: dict[str, Any]) -> None:
    resolved = resolve_refs(step, {"ui.a": {"id": "A"}, "ui.b": {"css": ".b"}})
    assert resolved == {"name": "s", "selector": {"id": "A"}}
