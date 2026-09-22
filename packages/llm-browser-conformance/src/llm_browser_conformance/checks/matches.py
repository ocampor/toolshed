"""``expect:`` and ``pick:`` — how many elements a step's selector may match,
and which of them it acts on.

Every check here runs against a page with three of everything, so a driver
that ignored the rule and took the first match is caught rather than averaged
away. The failure path is its own scenario: the count, the index and the text
samples in the message are exactly what drivers report differently.
"""

from pathlib import Path
from typing import Any

from llm_browser.results import BytesResult

from llm_browser_conformance.checks.support import (
    expect_failure,
    expect_success,
    texts,
)
from llm_browser_conformance.scenario import Context, Scenario, Section

PAGE = "match-rules.html"
SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"

# The actions `flows/match-rules.yaml` drives, one step each.
MATCH_STEPS = (
    "check",
    "click",
    "dom",
    "fill",
    "parse",
    "pick",
    "press",
    "read",
    "select",
    "type",
)


def row_value(ctx: Context, index: int) -> str:
    return ctx.value(f".row:nth-child({index + 1}) .name")


def png_height(data: bytes) -> int:
    """Height off a PNG's IHDR — enough to tell one row's crop from another's."""
    return int.from_bytes(data[20:24], "big")


def every_step_acts_on_the_match_its_pick_names(ctx: Context) -> None:
    outputs = expect_success(
        ctx, PAGE, "match-rules", schema_path=str(SCHEMAS_DIR / "label-row.yaml")
    )

    assert ctx.text("#clicked") == "Gamma", "click took a match other than `last`"
    assert row_value(ctx, 0) == "filled"
    assert row_value(ctx, 1) == "typed"
    assert row_value(ctx, 2) == "x", "press reached a row other than index 2"
    assert ctx.js("document.querySelectorAll('.flag')[2].checked") is True
    assert ctx.js("document.querySelectorAll('.flag')[0].checked") is False
    assert ctx.value(".row:nth-child(1) .choice") == "two"
    assert ctx.text("#picked") == "Gamma"

    assert texts(outputs, "read") == ["Gamma"]
    parsed: Any = outputs["parse"]
    assert [row["text"] for row in parsed] == ["Alpha"]
    assert "Beta" in str(outputs["dom"]), outputs["dom"]


def a_count_the_page_cannot_meet_fails_with_what_it_found(ctx: Context) -> None:
    """The message carries the count and a sample of the text, so an author
    who stated the wrong number can see which elements answered."""
    too_many = expect_failure(ctx, PAGE, "match-too-many").data
    assert getattr(too_many, "error", None) == "MatchCountError"
    assert getattr(too_many, "expected", None) == 1
    assert getattr(too_many, "found", None) == 3
    assert getattr(too_many, "samples", None) == ["Alpha", "Beta", "Gamma"]

    out_of_range = expect_failure(ctx, PAGE, "match-pick-range").data
    assert getattr(out_of_range, "error", None) == "PickRangeError"
    assert getattr(out_of_range, "expected", None) is None
    assert getattr(out_of_range, "found", None) == 3
    message = str(getattr(out_of_range, "message", out_of_range))
    assert "needs at least 6 matches" in message, message


def a_screenshot_crops_to_the_match_it_picked(ctx: Context) -> None:
    try:
        outputs = expect_success(ctx, PAGE, "match-screenshot")
    except NotImplementedError as exc:
        raise ctx.skip(str(exc)) from exc
    first, last = outputs["first"], outputs["last"]
    assert isinstance(first, BytesResult) and isinstance(last, BytesResult)
    assert png_height(first.content) < png_height(last.content), (
        f"first row captured {png_height(first.content)}px, "
        f"last row {png_height(last.content)}px"
    )


def a_download_takes_the_link_it_picked(ctx: Context) -> None:
    try:
        outputs = expect_success(ctx, "download.html", "match-download")
    except NotImplementedError as exc:
        raise ctx.skip(str(exc)) from exc
    payload = outputs["download"]
    assert isinstance(payload, BytesResult), payload
    assert payload.name == "alternate.txt", payload.name


SCENARIOS = [
    Scenario(
        "match per step",
        Section.STEPS,
        every_step_acts_on_the_match_its_pick_names,
        covers=frozenset(
            f"field:{action}.{rule}"
            for action in MATCH_STEPS
            for rule in ("expect", "pick")
        ),
    ),
    Scenario(
        "match count failure",
        Section.STEPS,
        a_count_the_page_cannot_meet_fails_with_what_it_found,
    ),
    Scenario(
        "match crops a screenshot",
        Section.STEPS,
        a_screenshot_crops_to_the_match_it_picked,
        covers=frozenset({"field:screenshot.expect", "field:screenshot.pick"}),
    ),
    Scenario(
        "match picks a file link",
        Section.STEPS,
        a_download_takes_the_link_it_picked,
        covers=frozenset({"field:download.expect", "field:download.pick"}),
    ),
]
