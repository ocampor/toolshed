"""Param registry: define reusable flow parameters, resolve and validate."""

from functools import lru_cache
from collections.abc import Sequence
from typing import Any

from yaml_engine.registry import Registry

from llm_browser.models import FlowData, Param


@lru_cache(maxsize=1)
def get_registry() -> Registry[Param]:
    return Registry("param")


register_param = get_registry().register


def resolve_params(raw_params: Sequence[str | dict[str, Any]]) -> dict[str, Param]:
    """Resolve a list of string refs and inline dicts into name->Param mapping.

    Bare strings are looked up in the registry; if not registered, they
    default to Param(required=True) so flows can declare params without
    pre-registering every name.
    """
    registry = get_registry()
    resolved: dict[str, Param] = {}
    for entry in raw_params:
        if isinstance(entry, str):
            try:
                resolved[entry] = registry.get(entry)
            except ValueError:
                resolved[entry] = Param(required=True)
        else:
            for name, definition in entry.items():
                resolved[name] = Param.model_validate(definition)
    return resolved


def validate_flow_params(
    raw_params: Sequence[str | dict[str, Any]], data: dict[str, object]
) -> FlowData:
    """Resolve params, validate data against them, apply defaults, return FlowData."""
    params = resolve_params(raw_params)
    fields: dict[str, Any] = {}
    for name, param in params.items():
        if name in data:
            fields[name] = data[name]
        elif not param.required:
            fields[name] = param.default
        else:
            raise ValueError(f"Missing required param: {name}")
    for name, value in data.items():
        if name not in fields:
            fields[name] = value
    return FlowData.model_validate(fields)


register_param("rfc", Param(required=True))
register_param("password", Param(required=True))
register_param("cp", Param(required=False, default=None))
