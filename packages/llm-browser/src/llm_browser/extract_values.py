"""Extracted rows typed through one pydantic row model per extract map, in pure
Python so every driver gets it without JS changes."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field, ValidationError, create_model

from llm_browser.constants import FAILED_ROWS_HINT, MATCH_SAMPLES
from llm_browser.extract_spec import ExtractSpec
from llm_browser.results import ExtractError
from llm_browser.selectors import MatchError

if TYPE_CHECKING:
    from llm_browser.parse import ExtractField

type Row = dict[str, Any]
type SpecKey = tuple[tuple[str, ExtractSpec], ...]


class FailedRowsError(MatchError):
    """Every row failed validation: the rot a green run with nulls hides."""

    def __init__(self, errors: list[ExtractError], rows: int) -> None:
        first = errors[0]
        super().__init__(
            f"every row failed, first row: {first.field}: {first.msg}",
            found=rows,
            samples=[f"{error.field}: {error.msg}" for error in errors[:MATCH_SAMPLES]],
            hint=FAILED_ROWS_HINT,
        )


@lru_cache(maxsize=64)
def row_model(fields: SpecKey) -> type[BaseModel]:
    # The extract name rides the alias: it need not be a Python identifier.
    columns: dict[str, Any] = {
        f"field_{i}": (
            Annotated[Any, BeforeValidator(spec.checked)],
            Field(None, alias=name),
        )
        for i, (name, spec) in enumerate(fields)
    }
    return create_model("ExtractedValues", **columns)


def extract_errors(index: int, exc: ValidationError) -> list[ExtractError]:
    return [
        ExtractError(
            row=index,
            field=str(error["loc"][0]),
            msg=error["msg"],
            input=error["input"],
        )
        for error in exc.errors()
    ]


def typed_row(
    model: type[BaseModel], index: int, row: Row
) -> tuple[Row, list[ExtractError]]:
    """A field that fails is left out and so stays at its ``None`` default."""
    try:
        return model.model_validate(row).model_dump(by_alias=True), []
    except ValidationError as exc:
        errors = extract_errors(index, exc)
    failed = {error.field for error in errors}
    kept = {name: value for name, value in row.items() if name not in failed}
    return model.model_validate(kept).model_dump(by_alias=True), errors


def typed_rows(
    rows: list[Row], extract: dict[str, ExtractField]
) -> tuple[list[Row], list[ExtractError]]:
    model = row_model(tuple((name, field.spec) for name, field in extract.items()))
    typed: list[Row] = []
    errors: list[ExtractError] = []
    for index, row in enumerate(rows):
        values, row_errors = typed_row(model, index, row)
        typed.append(values)
        errors.extend(row_errors)
    return typed, errors


def require_some_valid(rows: int, errors: list[ExtractError]) -> None:
    """Raises when every row failed; zero rows is no failure."""
    failed_rows = {error.row for error in errors}
    if rows and len(failed_rows) == rows:
        raise FailedRowsError(errors, rows)


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
