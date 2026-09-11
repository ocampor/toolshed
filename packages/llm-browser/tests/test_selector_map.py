"""Tests for selector map loading and ref resolution."""

from pathlib import Path

import yaml

from llm_browser.selector_map import load_selector_map, resolve_refs


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
    import pytest

    step = {"name": "s", "ref": "unknown.ref"}
    with pytest.raises(ValueError, match="selector ref 'unknown.ref' not found"):
        resolve_refs(step, {})


def test_resolve_refs_expands_every_selector_valued_key() -> None:
    """A step with more than one selector names each of them, so a `ref:`
    standing in for a selector is expanded wherever it appears."""
    selector_map = {
        "login.captcha": {"id": "captchaImg"},
        "login.captcha_answer": {"css": "#answer"},
    }
    step = {
        "name": "captcha",
        "action": "solve_captcha",
        "image": {"ref": "login.captcha"},
        "input": {"ref": "login.captcha_answer"},
        "submit": "#go",
    }
    result = resolve_refs(step, selector_map)
    assert result["image"] == {"id": "captchaImg"}
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
