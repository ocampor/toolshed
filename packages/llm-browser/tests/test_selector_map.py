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
