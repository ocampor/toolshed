"""Post-processing of extracted rows: each field's ``pattern``, ``type`` and
``required``, in pure Python so every driver gets it without JS changes."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, NamedTuple

from llm_browser.constants import INCOMPLETE_ROWS_HINT, MATCH_SAMPLES, META_KEY
from llm_browser.selectors import MatchError

if TYPE_CHECKING:
    from llm_browser.parse import ExtractField

type Value = str | int | float | None
type Row = dict[str, Any]

VALUE_CONVERTERS: dict[str, Callable[[str], Value]] = {
    "str": str,
    "int": int,
    "float": float,
}


class ExtractWarning(NamedTuple):
    field: str
    raw: str
    reason: str


class TypedValue(NamedTuple):
    value: Value
    failure: str = ""
    conversion_failed: bool = False


class IncompleteRowsError(MatchError):
    """Every row missed a required field: the rot a green run with nulls hides."""

    def __init__(self, incomplete: list[Row]) -> None:
        first_reasons = incomplete[0][META_KEY]["reasons"]
        super().__init__(
            f"every row is incomplete, first row: {'; '.join(first_reasons)}",
            found=len(incomplete),
            samples=[row[META_KEY]["reasons"][0] for row in incomplete[:MATCH_SAMPLES]],
            hint=INCOMPLETE_ROWS_HINT,
        )


def typed_value(field: ExtractField, raw: str | None) -> TypedValue:
    if raw is None:
        return TypedValue(None, "value was null")
    value = raw
    if field.pattern is not None:
        found = field.pattern.search(raw)
        if found is None:
            return TypedValue(
                None, f"no match for pattern {field.pattern.pattern!r} in {raw!r}"
            )
        value = found.group(1) if field.pattern.groups else found.group(0)
    if field.value_type == "str":
        return TypedValue(value)
    digits = value.replace(",", "").strip()
    if not digits:
        return TypedValue(None, f"blank value {raw!r}")
    try:
        return TypedValue(VALUE_CONVERTERS[field.value_type](digits))
    except ValueError:
        failure = f"could not convert {value!r} to {field.value_type}"
        return TypedValue(None, failure, conversion_failed=True)


def typed_row(
    row: Row, extract: dict[str, ExtractField], warnings: list[ExtractWarning]
) -> Row:
    typed: Row = {}
    reasons: list[str] = []
    for name, raw in row.items():
        result = typed_value(extract[name], raw)
        typed[name] = result.value
        if result.conversion_failed:
            warnings.append(ExtractWarning(name, raw, result.failure))
        if result.value is None and extract[name].required:
            reasons.append(f"{name}: required, {result.failure}")
    if reasons:
        typed[META_KEY] = {"incomplete": True, "reasons": reasons}
    return typed


def typed_rows(
    rows: list[Row], extract: dict[str, ExtractField]
) -> tuple[list[Row], list[ExtractWarning]]:
    """Raises when every row misses a required field; zero rows is no failure."""
    warnings: list[ExtractWarning] = []
    typed = [typed_row(row, extract, warnings) for row in rows]
    incomplete = [row for row in typed if META_KEY in row]
    if typed and len(incomplete) == len(typed):
        raise IncompleteRowsError(incomplete)
    return typed, warnings
