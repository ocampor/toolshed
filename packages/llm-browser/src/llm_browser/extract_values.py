"""Extracted rows typed field by field through one cached ``TypeAdapter`` per
spec, in pure Python so every driver gets it without JS changes."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import BeforeValidator, TypeAdapter, ValidationError

from llm_browser.constants import FAILED_ROWS_HINT, MATCH_SAMPLES
from llm_browser.extract_spec import ExtractSpec
from llm_browser.results import ExtractError
from llm_browser.selectors import MatchError

if TYPE_CHECKING:
    from llm_browser.parse import ExtractField

type Row = dict[str, Any]


class FailedRowsError(MatchError):
    """A required field failed on every row: the rot a green run with nulls hides."""

    def __init__(self, errors: list[ExtractError], rows: int) -> None:
        first = errors[0]
        super().__init__(
            f"every row failed, first row: {first.field}: {first.msg}",
            found=rows,
            samples=[f"{error.field}: {error.msg}" for error in errors[:MATCH_SAMPLES]],
            hint=FAILED_ROWS_HINT,
        )


@lru_cache(maxsize=256)
def field_adapter(spec: ExtractSpec) -> TypeAdapter[Any]:
    return TypeAdapter(Annotated[Any, BeforeValidator(spec.checked)])


def field_errors(index: int, name: str, exc: ValidationError) -> list[ExtractError]:
    return [
        ExtractError(row=index, field=name, msg=error["msg"], input=error["input"])
        for error in exc.errors()
    ]


def typed_row(
    index: int, row: Row, extract: dict[str, ExtractField]
) -> tuple[Row, list[ExtractError]]:
    """A field that fails is ``None``; the row's other fields stay typed."""
    values: Row = {}
    errors: list[ExtractError] = []
    for name, field in extract.items():
        try:
            values[name] = field_adapter(field.spec).validate_python(row.get(name))
        except ValidationError as exc:
            values[name] = None
            errors.extend(field_errors(index, name, exc))
    return values, errors


def typed_rows(
    rows: list[Row], extract: dict[str, ExtractField]
) -> tuple[list[Row], list[ExtractError]]:
    typed: list[Row] = []
    errors: list[ExtractError] = []
    for index, row in enumerate(rows):
        values, row_errors = typed_row(index, row, extract)
        typed.append(values)
        errors.extend(row_errors)
    return typed, errors


def require_some_valid(
    rows: int, errors: list[ExtractError], extract: dict[str, ExtractField]
) -> None:
    """Raises when a ``required`` field failed on every row; an optional
    field's error never fails the step, and zero rows is no failure."""
    required = {name for name, field in extract.items() if field.spec.required}
    failed = [error for error in errors if error.field in required]
    if rows and len({error.row for error in failed}) == rows:
        raise FailedRowsError(failed, rows)


def is_typed(field: ExtractField) -> bool:
    """A field whose raw value must reach Python whole, uncut, to be typed."""
    return field.spec.pattern is not None or field.spec.type != "str"


def preview_rows(
    rows: list[Row], extract: dict[str, ExtractField], limit: int
) -> list[Row]:
    """Rows as a real run types them, each string then cut to ``limit``."""
    typed, _ = typed_rows(rows, extract)
    return [{name: cut(value, limit) for name, value in row.items()} for row in typed]


def cut(value: Any, limit: int) -> Any:
    return value[:limit] if isinstance(value, str) else value
