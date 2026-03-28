"""Built-in condition operators and evaluation registry."""

import re
from functools import lru_cache
from typing import Callable, TypeVar

from yaml_engine.registry import Registry

T = TypeVar("T")

ConditionFn = Callable[..., bool]


@lru_cache(maxsize=1)
def get_registry() -> Registry[ConditionFn]:
    return Registry("condition operator")


register_condition = get_registry().register


def evaluate_condition(op: str, value: T, param: object) -> bool:
    """Evaluate a condition operator against a value and its compiled param."""
    return get_registry().get(op)(value, param)


# --- Built-in operators ---

@register_condition("eq")
def eq(value: T, param: T) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and isinstance(param, str):
        return value.lower() == param.lower()
    return bool(value == param)


@register_condition("neq")
def neq(value: T, param: T) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and isinstance(param, str):
        return value.lower() != param.lower()
    return bool(value != param)


@register_condition("contains")
def contains(value: T, param: str) -> bool:
    if value is None:
        return False
    return param.upper() in str(value).upper()


@register_condition("in")
def in_op(value: T, param: frozenset[str]) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.lower() in param
    return value in param


@register_condition("in_set")
def in_set(value: T, param: frozenset[str]) -> bool:
    return in_op(value, param)


@register_condition("all_present")
def all_present(value: T, param: list[str]) -> bool:
    """All substrings must be present in value (case-insensitive)."""
    if value is None:
        return False
    upper = str(value).upper()
    return all(s in upper for s in param)


@register_condition("has_fragment")
def has_fragment(value: T, param: list[str]) -> bool:
    """Any fragment in param must be present in value (case-insensitive)."""
    if value is None:
        return False
    upper = str(value).upper()
    return any(f in upper for f in param)


@register_condition("matches")
def matches(value: T, param: re.Pattern[str]) -> bool:
    if value is None:
        return False
    return bool(param.search(str(value)))


@register_condition("gt")
def gt(value: T, param: T) -> bool:
    if value is None:
        return False
    return bool(value > param)  # type: ignore[operator]


@register_condition("lt")
def lt(value: T, param: T) -> bool:
    if value is None:
        return False
    return bool(value < param)  # type: ignore[operator]


@register_condition("is_null")
def is_null(value: T, param: None) -> bool:
    return value is None


@register_condition("not_null")
def not_null(value: T, param: None) -> bool:
    return value is not None


@register_condition("is_truthy")
def is_truthy(value: T, param: None) -> bool:
    return bool(value)
