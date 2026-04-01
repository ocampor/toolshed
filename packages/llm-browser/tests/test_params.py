"""Tests for param resolution and validation."""

from typing import Any

import pytest

from llm_browser.params import resolve_params, validate_flow_params


def test_resolve_registered_param() -> None:
    params = resolve_params(["rfc"])
    assert "rfc" in params
    assert params["rfc"].required is True


def test_resolve_unregistered_param_defaults_to_required() -> None:
    params = resolve_params(["moneda_search"])
    assert "moneda_search" in params
    assert params["moneda_search"].required is True


def test_resolve_inline_param() -> None:
    params = resolve_params([{"tipo_cambio": {"required": False, "default": None}}])
    assert "tipo_cambio" in params
    assert params["tipo_cambio"].required is False
    assert params["tipo_cambio"].default is None


def test_resolve_mixed_params() -> None:
    raw: list[str | dict[str, Any]] = [
        "rfc",
        "moneda",
        {"tc": {"required": False, "default": "1.0"}},
    ]
    params = resolve_params(raw)
    assert len(params) == 3
    assert params["rfc"].required is True
    assert params["moneda"].required is True
    assert params["tc"].default == "1.0"


def test_validate_flow_params_required_present() -> None:
    raw: list[str | dict[str, Any]] = [
        "rfc",
        {"cp": {"required": False, "default": "00000"}},
    ]
    result = validate_flow_params(raw, {"rfc": "ABC010101000"})
    assert result.rfc == "ABC010101000"  # type: ignore[attr-defined]


def test_validate_flow_params_missing_required() -> None:
    with pytest.raises(ValueError, match="Missing required param"):
        validate_flow_params(["rfc"], {})


def test_validate_flow_params_default_applied() -> None:
    raw = [{"cp": {"required": False, "default": "00000"}}]
    result = validate_flow_params(raw, {})
    assert result.cp == "00000"  # type: ignore[attr-defined]


def test_validate_extra_data_passed_through() -> None:
    raw = ["rfc"]
    result = validate_flow_params(raw, {"rfc": "X", "extra_field": "Y"})
    assert result.extra_field == "Y"  # type: ignore[attr-defined]
