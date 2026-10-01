"""Typed ``read`` fields — ``pattern``, ``type``, ``required`` — and the
deprecated ``parse`` path's warning, as a run reports them."""

import datetime
from pathlib import Path

from llm_browser.constants import NUMBER_PATTERN, PARSE_DEPRECATED
from llm_browser.models import FlowSuccess
from llm_browser.results import ExtractWarning

from llm_browser_conformance.checks.support import error_message, expect_failure, run
from llm_browser_conformance.scenario import Context, Scenario, Section

PAGE = "typed-read.html"
SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"

TYPED_CARDS = [
    {
        "price": 48500,
        "lot": "252 m²",
        "bedrooms": 3,
        "rating": 4.5,
        "units": 1024,
        "published": datetime.date(2026, 10, 1),
        "updated": datetime.date(2026, 9, 30),
        "listed": datetime.date(2026, 10, 1),
        "due": datetime.date(2026, 10, 5),
    },
    {
        "price": None,
        "lot": "180 m²",
        "bedrooms": None,
        "rating": None,
        "units": None,
        "published": None,
        "updated": datetime.date(2026, 9, 15),
        "listed": datetime.date(2026, 9, 15),
        "due": datetime.date(2026, 10, 20),
        "_meta": {
            "incomplete": True,
            "reasons": [
                (
                    f"price: required, no match for pattern {NUMBER_PATTERN!r} "
                    "in 'Consultar precio'"
                )
            ],
        },
    },
]


def typed_fields_come_back_converted(ctx: Context) -> None:
    result = run(ctx, PAGE, "typed-read")

    assert isinstance(result, FlowSuccess), f"{result.step}: {result.data}"
    assert result.outputs["cards"] == TYPED_CARDS
    assert result.extract_warnings == [
        ExtractWarning(
            step="cards",
            field="published",
            raw="n/a",
            reason="could not parse 'n/a' as a date",
        )
    ]


def a_required_field_no_row_has_fails_the_step(ctx: Context) -> None:
    failure = expect_failure(ctx, PAGE, "typed-read-rot")
    assert failure.step == "cards"
    assert "price: required, value was null" in error_message(failure)


def parse_warns_once_per_run(ctx: Context) -> None:
    result = run(
        ctx,
        "parse-table.html",
        "parse-deprecated",
        schema_path=str(SCHEMAS_DIR / "table-row.yaml"),
    )

    assert isinstance(result, FlowSuccess), f"{result.step}: {result.data}"
    assert [row["name"] for row in result.outputs["first"]] == ["widget"]  # type: ignore[attr-defined]
    assert result.extract_warnings == [
        ExtractWarning(step="first", field="parse", raw="", reason=PARSE_DEPRECATED)
    ]


SCENARIOS = [
    Scenario(
        "typed read values",
        Section.STEPS,
        typed_fields_come_back_converted,
        covers=frozenset(
            {
                "api:extract.pattern",
                "api:extract.type",
                "api:extract.required",
                "api:extract_warnings",
                "api:extract.format",
                "api:extract.date_order",
                "api:extract.languages",
            }
        ),
    ),
    Scenario(
        "required field rot",
        Section.STEPS,
        a_required_field_no_row_has_fails_the_step,
        covers=frozenset({"api:extract.required"}),
    ),
    Scenario(
        "parse deprecation",
        Section.STEPS,
        parse_warns_once_per_run,
        covers=frozenset(
            {"api:parse.deprecated", "field:parse.expect", "field:parse.pick"}
        ),
    ),
]
