"""Post-processing of extracted rows: each field's ``pattern``, ``type`` and
``required``, in pure Python so every driver gets it without JS changes."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, NamedTuple

from llm_browser.constants import INCOMPLETE_ROWS_HINT, MATCH_SAMPLES, META_KEY
from llm_browser.results import ExtractWarning
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
        picked = None
        if found is not None:
            picked = found.group(1) if field.pattern.groups else found.group(0)
        # An optional group 1 can match nothing: that is no match too.
        if picked is None:
            return TypedValue(
                None, f"no match for pattern {field.pattern.pattern!r} in {raw!r}"
            )
        value = picked
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
            warnings.append(ExtractWarning(field=name, raw=raw, reason=result.failure))
        if result.value is None and extract[name].required:
            reasons.append(f"{name}: required, {result.failure}")
    if reasons:
        typed[META_KEY] = {"incomplete": True, "reasons": reasons}
    return typed


def typed_rows(
    rows: list[Row], extract: dict[str, ExtractField]
) -> tuple[list[Row], list[ExtractWarning]]:
    warnings: list[ExtractWarning] = []
    typed = [typed_row(row, extract, warnings) for row in rows]
    return typed, warnings


def require_complete(rows: list[Row]) -> None:
    """Raises when every row misses a required field; zero rows is no failure."""
    incomplete = [row for row in rows if META_KEY in row]
    if rows and len(incomplete) == len(rows):
        raise IncompleteRowsError(incomplete)


def is_typed(field: ExtractField) -> bool:
    """A field whose raw value must reach Python whole, uncut, to be typed."""
    return field.pattern is not None or field.value_type != "str"


def preview_rows(
    rows: list[Row], extract: dict[str, ExtractField], limit: int
) -> list[Row]:
    """Rows as a real run types them, each string then cut to ``limit``."""
    typed, _ = typed_rows(rows, extract)
    return [{name: cut(value, limit) for name, value in row.items()} for row in typed]


def cut(value: Any, limit: int) -> Any:
    """Every string, however deep — ``_meta`` reasons quote the raw value whole."""
    match value:
        case str():
            return value[:limit]
        case dict():
            return {key: cut(item, limit) for key, item in value.items()}
        case list():
            return [cut(item, limit) for item in value]
        case _:
            return value
