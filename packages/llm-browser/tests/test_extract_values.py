"""Tests for typed extract fields: pattern, type and required."""

import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from llm_browser.extract_values import FailedRowsError, require_some_valid, typed_rows
from llm_browser.flows import run_flow
from llm_browser.actions import execute_action
from llm_browser.models import Flow, FlowSuccess, ParseStep
from llm_browser.parse import ExtractField, build_model, parse_extract_spec
from llm_browser.results import ExtractError, ParsedResult
from llm_browser.session import BrowserSession
from tests.conftest import ExploringSession
from tests.extract_helpers import CARD_EXTRACT, CARDS, TYPED_CARDS, serve_rows

PRICE = ExtractField(pattern=r"([\d,]+)", type="int", required=True)


def typed_one(
    field: ExtractField, raw: str | None
) -> tuple[object, list[ExtractError]]:
    rows, warnings = typed_rows([{"v": raw}], {"v": field})
    return rows[0]["v"], warnings


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        (ExtractField(pattern=r"(\d+) rec"), "252 m² lote3 baños", None),
        (ExtractField(pattern=r"(\d+) rec"), "3 rec. 4 baños", "3"),
        (ExtractField(pattern=r"\d+ m²"), "lote 252 m² x", "252 m²"),
        (ExtractField(type="int"), "MN 48,500", 48500),
        (ExtractField(type="int"), "252 m² lote 3 rec. 4 baños", 252),
        (ExtractField(pattern=r"(\d+) rec", type="int"), "252 m² lote 3 rec. 4", 3),
        (ExtractField(type="int"), "-15", -15),
        (ExtractField(type="int"), "1,50", 150),
        (ExtractField(type="float"), "1,234.5", 1234.5),
        (ExtractField(type="float"), "4.5", 4.5),
        (ExtractField(type="int"), " ", None),
        (ExtractField(type="int"), None, None),
        (ExtractField(type="date"), "2026-10-01", date(2026, 10, 1)),
        (
            ExtractField(type="date", languages=["es"]),
            "1 de octubre de 2026",
            date(2026, 10, 1),
        ),
        (ExtractField(type="date"), "01/10/2026", date(2026, 1, 10)),
        (ExtractField(type="date", date_order="DMY"), "01/10/2026", date(2026, 10, 1)),
        (
            ExtractField(type="datetime", format="%d/%m/%Y %H:%M"),
            "01/10/2026 14:30",
            datetime(2026, 10, 1, 14, 30),
        ),
        (
            ExtractField(type="datetime"),
            "2026-10-01 14:30",
            datetime(2026, 10, 1, 14, 30),
        ),
        (ExtractField(type="date"), " ", None),
        (ExtractField(type="date", format="%d/%m/%Y"), "01/10/2026", date(2026, 10, 1)),
    ],
)
def test_typed_value(field: ExtractField, raw: str | None, expected: object) -> None:
    assert typed_one(field, raw) == (expected, [])


@pytest.mark.parametrize(
    ("field", "raw", "msg"),
    [
        (ExtractField(type="int"), "4.5", "could not convert '4.5' to int"),
        (ExtractField(type="date"), "n/a", "could not parse 'n/a' as a date"),
        (
            ExtractField(type="date", format="%d/%m/%Y"),
            "05/10/26",
            "could not parse '05/10/26' as a date",
        ),
        (
            ExtractField(type="date", languages=["es"]),
            "marzo 2026",
            "could not parse 'marzo 2026' as a date",
        ),
        (ExtractField(type="date"), "3", "could not parse '3' as a date"),
        (
            ExtractField(type="date", languages=["sp"]),
            "1 oct 2026",
            "Unknown language(s): 'sp'",
        ),
    ],
)
def test_a_failed_field_is_null_plus_an_error(
    field: ExtractField, raw: str, msg: str
) -> None:
    assert typed_one(field, raw) == (
        None,
        [ExtractError(row=0, field="v", msg=f"Value error, {msg}", input=raw)],
    )


@pytest.mark.parametrize(
    ("pattern", "raw"), [(r"(\d+)? ?rec", "rec"), (r"(\d+)|n/a", "n/a")]
)
@pytest.mark.parametrize("value_type", ["int", "str"])
def test_an_unmatched_group_is_no_match(
    pattern: str, raw: str, value_type: str
) -> None:
    field = ExtractField(pattern=pattern, type=value_type, required=True)

    (row,), errors = typed_rows([{"v": raw}], {"v": field})

    assert row["v"] is None
    assert [error.msg for error in errors] == [
        f"Value error, required, nothing read from {raw!r}"
    ]


def test_blank_converts_to_null_without_error() -> None:
    assert typed_rows([{"n": ""}], {"n": ExtractField(type="int")}) == (
        [{"n": None}],
        [],
    )


def test_required_errors_only_the_rows_that_miss() -> None:
    extract = {"price": PRICE, "name": ExtractField()}
    rows = [
        {"price": "MN 48,500", "name": "a"},
        {"price": "Consultar precio", "name": "b"},
        {"price": None, "name": "c"},
    ]

    typed, errors = typed_rows(rows, extract)

    assert typed == [
        {"price": 48500, "name": "a"},
        {"price": None, "name": "b"},
        {"price": None, "name": "c"},
    ]
    assert [(error.row, error.field, error.input) for error in errors] == [
        (1, "price", "Consultar precio"),
        (2, "price", None),
    ]


def test_a_failed_field_keeps_the_rest_of_the_row() -> None:
    extract = {"n": ExtractField(type="int"), "ok": ExtractField()}

    typed, errors = typed_rows([{"n": "4.5", "ok": "y"}], extract)

    assert typed == [{"n": None, "ok": "y"}]
    assert [error.field for error in errors] == ["n"]


def test_every_row_failing_raises() -> None:
    rows, errors = typed_rows([{"price": "Consultar precio"}], {"price": PRICE})

    with pytest.raises(FailedRowsError, match="price.*'Consultar precio'"):
        require_some_valid(len(rows), errors)


def test_zero_rows_is_no_failure() -> None:
    require_some_valid(0, [])


@pytest.fixture
def session(tmp_path: Path) -> BrowserSession:
    s = BrowserSession(state_dir=tmp_path)
    s._page = MagicMock()
    return s


@pytest.mark.parametrize(
    "spec",
    [
        {"name": "td.name", "url": "a@href"},
        {
            "name": {"child_selector": "td.name"},
            "url": {"child_selector": "a", "attribute": "href"},
        },
    ],
)
def test_untyped_spec_is_byte_identical(
    session: BrowserSession, spec: dict[str, object]
) -> None:
    baseline = [{"name": " Alice ", "url": ""}, {"name": "", "url": None}]
    serve_rows(session, [dict(row) for row in baseline])

    rows = session.parse_elements("tr", parse_extract_spec(spec))

    assert json.dumps(rows) == json.dumps(baseline)


def test_each_parse_elements_call_replaces_the_errors(
    session: BrowserSession,
) -> None:
    """Outside any step (a `find`), the list must not grow without bound."""
    extract = {"n": ExtractField(type="int")}
    serve_rows(session, [{"n": "1,200"}, {"n": "4.5"}])
    first = session.parse_elements("tr", extract)
    serve_rows(session, [{"n": "8"}, {"n": "7.5"}])
    session.parse_elements("tr", extract)

    assert first == [{"n": 1200}, {"n": None}]
    assert session.extract_errors == [
        ExtractError(
            row=1,
            field="n",
            msg="Value error, could not convert '7.5' to int",
            input="7.5",
        )
    ]


def read_flow(extract: dict[str, object]) -> dict[str, object]:
    return {
        "steps": [{"name": "s", "action": "read", "selector": "tr", "extract": extract}]
    }


@pytest.mark.parametrize(
    "extract",
    [
        {"price": {"pattern": "("}},
        {"price": {"type": "bool"}},
        {"price": {"type": "int", "format": "%d"}},
        {"price": {"child": "td"}},
    ],
)
def test_invalid_extract_rejected_at_validation(extract: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Flow.model_validate(read_flow(extract))


def test_invalid_pattern_names_the_pattern() -> None:
    with pytest.raises(ValueError, match="invalid pattern '\\('"):
        ExtractField(pattern="(")


def test_explore_previews_the_rows_a_typed_read_returns(
    session: BrowserSession, exploring_session: ExploringSession
) -> None:
    serve_rows(session, [{"price": r[".price"], "rooms": r[".label"]} for r in CARDS])
    extract = parse_extract_spec(CARD_EXTRACT)

    result = exploring_session(CARDS).explore(".card", extract=extract)

    assert session.parse_elements(".card", extract) == TYPED_CARDS
    assert result.sample == TYPED_CARDS
    assert result.empty_fields == ["rooms"]


def test_an_unmatched_group_leaves_the_run_green(
    session: BrowserSession, tmp_path: Path
) -> None:
    serve_rows(session, [{"beds": "rec"}, {"beds": "3 rec"}])
    extract = {"beds": {"pattern": r"(\d+)? ?rec", "type": "int"}}
    flow = Flow.model_validate(read_flow(extract))

    result = run_flow(session, flow, {})

    assert isinstance(result, FlowSuccess), result
    assert result.outputs["s"] == [None, {"beds": 3}]


def test_a_schema_pattern_constrains_a_parse_step(
    session: BrowserSession, tmp_path: Path
) -> None:
    schema = tmp_path / "row.yaml"
    schema.write_text(
        "name: Row\nfields:\n  id: {type: str, pattern: '^[A-Z]{3}$', child_selector: .a}\n"
    )
    Row = build_model(schema)
    serve_rows(session, [{"id": "ABC"}])
    step = ParseStep(name="s", action="parse", selector="tr", schema_path=str(schema))

    assert isinstance(Row._spec()["id"], ExtractField)
    assert Row.model_validate({"id": "ABC"}).id == "ABC"
    with pytest.raises(ValidationError):
        Row.model_validate({"id": "id ABC-12"})
    result = execute_action(session, step)
    assert isinstance(result, ParsedResult), result
    assert [row.id for row in result.rows] == ["ABC"]
