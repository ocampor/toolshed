"""Post-processing of extracted rows: each field's ``pattern``, ``type`` and
``required``, in pure Python so every driver gets it without JS changes."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import BaseModel, Field, create_model

from llm_browser.constants import INCOMPLETE_ROWS_HINT, MATCH_SAMPLES, META_KEY
from llm_browser.extract_spec import ExtractSpec
from llm_browser.extractors import get_extractors
from llm_browser.results import ExtractWarning
from llm_browser.selectors import MatchError

if TYPE_CHECKING:
    from llm_browser.parse import ExtractField

type Row = dict[str, Any]
type SpecKey = tuple[tuple[str, ExtractSpec], ...]


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


def row_field(name: str, spec: ExtractSpec) -> Any:
    extractor = get_extractors().get(spec.type)(name, spec)
    optional: Any = extractor.py_type | None
    # The extract name rides the alias: it need not be a Python identifier.
    return (Annotated[optional, extractor], Field(None, alias=name))


@lru_cache(maxsize=64)
def row_model(fields: SpecKey) -> type[BaseModel]:
    columns = {
        f"field_{i}": row_field(name, spec) for i, (name, spec) in enumerate(fields)
    }
    return create_model("ExtractedValues", **columns)


def incomplete_reasons(
    row: Row, extract: dict[str, ExtractField], reasons: dict[str, str]
) -> list[str]:
    return [
        f"{name}: required, {reasons.get(name, 'value was null')}"
        for name, field in extract.items()
        if field.spec.required and row.get(name) is None
    ]


def with_meta(row: Row, reasons: list[str]) -> Row:
    if not reasons:
        return row
    return {**row, META_KEY: {"incomplete": True, "reasons": reasons}}


def typed_row(
    row: Row, extract: dict[str, ExtractField], warnings: list[ExtractWarning]
) -> Row:
    model = row_model(tuple((name, field.spec) for name, field in extract.items()))
    reasons: dict[str, str] = {}
    context = {"row": row, "reasons": reasons, "warnings": warnings}
    typed = model.model_validate(row, context=context).model_dump(by_alias=True)
    return with_meta(typed, incomplete_reasons(typed, extract, reasons))


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
    return field.spec.pattern is not None or field.spec.type != "str"


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
