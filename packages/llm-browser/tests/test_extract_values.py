"""Tests for typed extract fields: pattern, type and required."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from llm_browser.constants import META_KEY
from llm_browser.extract_values import (
    IncompleteRowsError,
    require_complete,
    typed_rows,
    typed_value,
)
from llm_browser.models import Flow
from llm_browser.parse import ExtractField, parse_extract_spec
from llm_browser.results import ExtractWarning
from llm_browser.session import BrowserSession
from tests.conftest import ExploringSession

PRICE = ExtractField(pattern=r"([\d,]+)", type="int", required=True)


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        (ExtractField(pattern=r"(\d+) rec"), "252 m² lote3 baños", None),
        (ExtractField(pattern=r"(\d+) rec"), "3 rec. 4 baños", "3"),
        (ExtractField(pattern=r"\d+ m²"), "lote 252 m² x", "252 m²"),
        (ExtractField(type="int"), "MN 48,500", None),
        (ExtractField(pattern=r"([\d,]+)", type="int"), "MN 48,500", 48500),
        (ExtractField(type="float"), "1,234.5", 1234.5),
        (ExtractField(type="int"), " ", None),
        (ExtractField(type="int"), None, None),
    ],
)
def test_typed_value(field: ExtractField, raw: str | None, expected: object) -> None:
    assert typed_value(field, raw).value == expected


def test_blank_converts_to_null_without_warning() -> None:
    assert typed_rows([{"n": ""}], {"n": ExtractField(type="int")}) == (
        [{"n": None}],
        [],
    )


def test_failed_conversion_warns() -> None:
    rows, warnings = typed_rows([{"n": "abc"}], {"n": ExtractField(type="float")})

    assert rows == [{"n": None}]
    assert warnings == [
        ExtractWarning(field="n", raw="abc", reason="could not convert 'abc' to float")
    ]


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

    typed, _ = typed_rows([{"n": "x", "ok": "y"}, {"n": "1", "ok": "y"}], extract)

    assert typed[0][META_KEY]["reasons"] == [
        "n: required, could not convert 'x' to int"
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


def serve_rows(session: BrowserSession, rows: list[dict[str, str | None]]) -> None:
    locator = MagicMock()
    locator.evaluate_all.return_value = rows
    session._page.locator.return_value = locator  # type: ignore[union-attr]


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


def test_parse_elements_types_rows_and_keeps_warnings(session: BrowserSession) -> None:
    serve_rows(session, [{"n": "1,200"}, {"n": "x"}])

    with session.matching(None):
        rows = session.parse_elements("tr", {"n": ExtractField(type="int")})
        warnings = list(session.extract_warnings)

    assert rows == [{"n": 1200}, {"n": None}]
    assert warnings == [
        ExtractWarning(field="n", raw="x", reason="could not convert 'x' to int")
    ]
    assert session.extract_warnings == []


def read_flow(extract: dict[str, object]) -> dict[str, object]:
    return {
        "steps": [{"name": "s", "action": "read", "selector": "tr", "extract": extract}]
    }


@pytest.mark.parametrize(
    "extract",
    [
        {"price": {"pattern": "("}},
        {"price": {"type": "bool"}},
        {META_KEY: "td"},
    ],
)
def test_invalid_extract_rejected_at_validation(extract: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Flow.model_validate(read_flow(extract))


def test_invalid_pattern_names_the_pattern() -> None:
    with pytest.raises(ValueError, match="invalid pattern '\\('"):
        ExtractField(pattern="(")


# What a typed read returns for CARDS, and so what explore must preview.
CARDS = [
    {".price": "MN 48,500", ".label": "Casa 3 rec"},
    {".price": "Consultar precio", ".label": "Casa"},
]
CARD_EXTRACT = {
    "price": {
        "child_selector": ".price",
        "pattern": r"([\d,]+)",
        "type": "int",
        "required": True,
    },
    "rooms": {"child_selector": ".label", "pattern": r"(\d+) baños"},
}
TYPED_CARDS = [
    {"price": 48500, "rooms": None},
    {
        "price": None,
        "rooms": None,
        META_KEY: {
            "incomplete": True,
            "reasons": [
                r"price: required, no match for pattern '([\\d,]+)' in 'Consultar precio'"
            ],
        },
    },
]


def test_explore_previews_the_rows_a_typed_read_returns(
    session: BrowserSession, exploring_session: ExploringSession
) -> None:
    serve_rows(session, [{"price": r[".price"], "rooms": r[".label"]} for r in CARDS])
    extract = parse_extract_spec(CARD_EXTRACT)

    result = exploring_session(CARDS).explore(".card", extract=extract)

    assert session.parse_elements(".card", extract) == TYPED_CARDS
    assert result.sample == TYPED_CARDS
    assert result.empty_fields == ["rooms"]
