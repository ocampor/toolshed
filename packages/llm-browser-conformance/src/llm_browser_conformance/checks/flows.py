"""Flow-level conformance: what a caller gets back when a step fails.

The library's promise is that a failed step is a value, not an exception, that
the value carries enough to retry or hand to a human, and that it is all in
memory — so these check the captures the caller gets back, the
``human_needed`` verdict, and that nothing was written anywhere.
"""

import datetime
import decimal
import tempfile
from pathlib import Path

from llm_browser.flows import run_flow
from llm_browser.models import FlowError, FlowSuccess

from llm_browser_conformance.checks.support import expect_success, wrote_nothing
from llm_browser_conformance.scenario import Context, Scenario, Section

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def a_failing_wait_step_captures_screenshot_and_dom_in_memory(ctx: Context) -> None:
    ctx.visit("never.html")
    with wrote_nothing(ctx):
        result = run_flow(ctx.session, ctx.flow("wait-never"), {})
    assert isinstance(result, FlowError), result
    assert result.step == "wait-never"
    assert isinstance(result.screenshot, bytes)
    assert result.screenshot.startswith(PNG_MAGIC), result.screenshot[:16]
    assert isinstance(result.dom, str)
    assert "<html" in result.dom and "<script" not in result.dom
    assert result.human_needed is False


def a_failure_behind_a_login_wall_asks_for_a_human(ctx: Context) -> None:
    ctx.visit("login-wall.html")
    result = run_flow(ctx.session, ctx.flow("wait-never"), {})
    assert isinstance(result, FlowError), result
    assert result.human_needed is True


def a_screenshot_is_a_png(ctx: Context) -> None:
    """Everything above the driver calls these bytes a PNG and hands them to a
    reader that believes it, so the bytes have to match."""
    ctx.visit("form.html")
    assert ctx.session.screenshot_bytes()[:8] == PNG_MAGIC


def a_parse_step_returns_typed_rows_and_ignores_its_path(ctx: Context) -> None:
    """``Decimal`` and ``date`` are the point: the rows come back coerced, and
    a caller that wants JSON gets it from a json-mode dump.

    ``path:`` is an instruction to the CLI — the runner has to leave it alone.
    """
    with tempfile.TemporaryDirectory() as directory:
        out = Path(directory) / "rows.json"
        outputs = expect_success(
            ctx,
            "parse-rows.html",
            "parse-rows",
            schema=str(SCHEMAS_DIR / "invoice.yaml"),
            out=str(out),
        )
        assert not out.exists(), "`path:` is CLI-only; the runner wrote a file"
    rows = outputs["rows"]
    assert isinstance(rows, list)
    assert [row["name"] for row in rows] == ["alpha", "beta"]
    assert rows[0]["total"] == decimal.Decimal("10.25")
    assert rows[0]["due"] == datetime.date(2024, 3, 1)


def an_optional_wait_step_turns_a_timeout_into_a_skip(ctx: Context) -> None:
    ctx.visit("never.html")
    result = run_flow(ctx.session, ctx.flow("wait-never-optional"), {})
    assert isinstance(result, FlowSuccess), result


SCENARIOS = [
    Scenario(
        "flow failure captures artifacts",
        Section.FLOWS,
        a_failing_wait_step_captures_screenshot_and_dom_in_memory,
        covers=frozenset(
            {
                "field:wait_for.selector",
                "field:wait_for.state",
                "session:dom_snapshot",
                "session:screenshot_bytes",
                "step:wait_for",
            }
        ),
    ),
    Scenario(
        "flow failure flags a login wall",
        Section.FLOWS,
        a_failure_behind_a_login_wall_asks_for_a_human,
        covers=frozenset({"api:human_needed.password", "session:probe"}),
    ),
    Scenario(
        "screenshot is a png",
        Section.FLOWS,
        a_screenshot_is_a_png,
        covers=frozenset({"session:screenshot_bytes"}),
    ),
    Scenario(
        "parse decimal and date rows",
        Section.FLOWS,
        a_parse_step_returns_typed_rows_and_ignores_its_path,
        covers=frozenset({"field:parse.path"}),
    ),
    Scenario(
        "optional step swallows a timeout",
        Section.FLOWS,
        an_optional_wait_step_turns_a_timeout_into_a_skip,
        covers=frozenset({"option:optional"}),
    ),
]
