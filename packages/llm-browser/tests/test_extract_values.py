"""Tests for typed extract fields: pattern, type and required."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from llm_browser.constants import META_KEY
from llm_browser.extract_values import (
    IncompleteRowsError,
    require_complete,
    typed_rows,
)
from llm_browser.flows import run_flow
from llm_browser.actions import execute_action
from llm_browser.models import Flow, FlowSuccess, ParseStep
from llm_browser.parse import ExtractField, build_model, parse_extract_spec
from llm_browser.results import ExtractWarning, ParsedResult
from llm_browser.session import BrowserSession
from tests.conftest import ExploringSession
from tests.extract_helpers import CARD_EXTRACT, CARDS, TYPED_CARDS, serve_rows

PRICE = ExtractField(pattern=r"([\d,]+)", type="int", required=True)


def typed_one(
    field: ExtractField, raw: str | None
) -> tuple[object, list[ExtractWarning]]:
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
        (ExtractField(type="date", date_order="DMY"), "2026-10-01", date(2026, 10, 1)),
        (ExtractField(type="date", format="%d/%m/%Y"), "01/10/2026", date(2026, 10, 1)),
    ],
)
def test_typed_value(field: ExtractField, raw: str | None, expected: object) -> None:
    assert typed_one(field, raw) == (expected, [])


@pytest.mark.parametrize(
    ("field", "raw", "reason"),
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
        (ExtractField(type="date"), "2026", "could not parse '2026' as a date"),
    ],
)
def test_failed_conversion_warns(field: ExtractField, raw: str, reason: str) -> None:
    assert typed_one(field, raw) == (
        None,
        [ExtractWarning(field="v", raw=raw, reason=reason)],
    )


@pytest.mark.parametrize(
    ("pattern", "raw"), [(r"(\d+)? ?rec", "rec"), (r"(\d+)|n/a", "n/a")]
)
@pytest.mark.parametrize("value_type", ["int", "str"])
def test_an_unmatched_group_is_no_match(
    pattern: str, raw: str, value_type: str
) -> None:
    field = ExtractField(pattern=pattern, type=value_type, required=True)

    (row,), warnings = typed_rows([{"v": raw}], {"v": field})

    assert row["v"] is None and warnings == []
    assert row[META_KEY]["reasons"] == [
        f"v: required, no match for pattern {pattern!r} in {raw!r}"
    ]


def test_blank_converts_to_null_without_warning() -> None:
    assert typed_rows([{"n": ""}], {"n": ExtractField(type="int")}) == (
        [{"n": None}],
        [],
    )


def test_required_marks_only_incomplete_rows() -> None:
    extract = {"price": PRICE, "name": ExtractField()}
    rows = [
        {"price": "MN 48,500", "name": "a"},
        {"price": "Consultar precio", "name": "b"},
        {"price": None, "name": "c"},
    ]

    typed, _ = typed_rows(rows, extract)

    assert typed[0] == {"price": 48500, "name": "a"}
    assert typed[1][META_KEY] == {
        "incomplete": True,
        "reasons": [
            r"price: required, no match for pattern '([\\d,]+)' in 'Consultar precio'"
        ],
    }
    assert typed[2][META_KEY]["reasons"] == ["price: required, value was null"]


def test_required_conversion_failure_reason() -> None:
    extract = {"n": ExtractField(type="int", required=True), "ok": ExtractField()}

    typed, _ = typed_rows([{"n": "4.5", "ok": "y"}, {"n": "1", "ok": "y"}], extract)

    assert typed[0][META_KEY]["reasons"] == [
        "n: required, could not convert '4.5' to int"
    ]


def test_every_row_incomplete_raises() -> None:
    rows, _ = typed_rows([{"price": "Consultar precio"}], {"price": PRICE})

    with pytest.raises(IncompleteRowsError, match="price.*'Consultar precio'"):
        require_complete(rows)


def test_zero_rows_is_no_failure() -> None:
    require_complete([])


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


def test_each_parse_elements_call_replaces_the_warnings(
    session: BrowserSession,
) -> None:
    """Outside any step (a `find`), the list must not grow without bound."""
    extract = {"n": ExtractField(type="int")}
    serve_rows(session, [{"n": "1,200"}, {"n": "4.5"}])
    first = session.parse_elements("tr", extract)
    serve_rows(session, [{"n": "7.5"}])
    session.parse_elements("tr", extract)

    assert first == [{"n": 1200}, {"n": None}]
    assert session.extract_warnings == [
        ExtractWarning(field="n", raw="7.5", reason="could not convert '7.5' to int")
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
        {"due": {"type": "date", "format": "%Q"}},
        {"due": {"type": "date", "languages": ["sp"]}},
        {"price": {"child": "td"}},
        {META_KEY: "td"},
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


def test_explore_cuts_the_raw_text_its_reasons_quote(
    exploring_session: ExploringSession,
) -> None:
    extract = parse_extract_spec(
        {"n": {"child_selector": ".n", "type": "int", "required": True}}
    )
    rows = [{".n": "x" * 5000}, {".n": "7"}]

    (incomplete, _) = (
        exploring_session(rows).explore(".row", extract=extract, sample_chars=40).sample
    )

    assert all(len(reason) <= 40 for reason in incomplete[META_KEY]["reasons"])


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
