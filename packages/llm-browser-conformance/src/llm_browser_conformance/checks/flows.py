"""Flow-level conformance: what a caller gets back when a step fails.

The library's promise is that a failed step is a value, not an exception, and
that the value carries enough to retry or hand to a human — so these check the
artifacts on disk and the ``human_needed`` verdict, not just the failure.
"""

import json
import tempfile
from pathlib import Path

from llm_browser.flows import run_flow
from llm_browser.models import FlowError, FlowSuccess

from llm_browser_conformance.checks.support import expect_success
from llm_browser_conformance.scenario import Context, Scenario, Section

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def a_failing_wait_step_captures_screenshot_and_dom(ctx: Context) -> None:
    ctx.visit("never.html")
    result = run_flow(ctx.session, ctx.flow("wait-never"), {})
    assert isinstance(result, FlowError), result
    assert result.step == "wait-never"
    assert result.screenshot is not None and Path(result.screenshot).exists()
    assert result.dom is not None and Path(result.dom).exists()
    assert result.human_needed is False


def a_failure_behind_a_login_wall_asks_for_a_human(ctx: Context) -> None:
    ctx.visit("login-wall.html")
    result = run_flow(ctx.session, ctx.flow("wait-never"), {})
    assert isinstance(result, FlowError), result
    assert result.human_needed is True


def a_screenshot_is_a_png(ctx: Context) -> None:
    """Everything above the driver names the file `.png` and hands it to a
    reader that trusts the extension, so the bytes have to match it."""
    ctx.visit("form.html")
    assert ctx.session.take_screenshot().read_bytes()[:8] == PNG_MAGIC
    assert ctx.session.screenshot_bytes()[:8] == PNG_MAGIC


def a_parse_step_writes_its_typed_rows_to_disk(ctx: Context) -> None:
    """``Decimal`` and ``date`` are the point: a python-mode dump hands them
    to ``json.dumps``, which cannot represent either, and the crash escapes
    ``run_flow`` instead of coming back as a failed step."""
    with tempfile.TemporaryDirectory() as directory:
        out = Path(directory) / "rows.json"
        expect_success(
            ctx,
            "parse-rows.html",
            "parse-rows",
            schema=str(SCHEMAS_DIR / "invoice.yaml"),
            out=str(out),
        )
        assert json.loads(out.read_text()) == [
            {"name": "alpha", "total": "10.25", "due": "2024-03-01"},
            {"name": "beta", "total": "7.50", "due": "2024-04-15"},
        ]


def an_optional_wait_step_turns_a_timeout_into_a_skip(ctx: Context) -> None:
    ctx.visit("never.html")
    result = run_flow(ctx.session, ctx.flow("wait-never-optional"), {})
    assert isinstance(result, FlowSuccess), result


SCENARIOS = [
    Scenario(
        "flow failure captures artifacts",
        Section.FLOWS,
        a_failing_wait_step_captures_screenshot_and_dom,
    ),
    Scenario(
        "flow failure flags a login wall",
        Section.FLOWS,
        a_failure_behind_a_login_wall_asks_for_a_human,
    ),
    Scenario(
        "screenshot is a png",
        Section.FLOWS,
        a_screenshot_is_a_png,
    ),
    Scenario(
        "parse writes typed rows",
        Section.FLOWS,
        a_parse_step_writes_its_typed_rows_to_disk,
    ),
    Scenario(
        "optional step swallows a timeout",
        Section.FLOWS,
        an_optional_wait_step_turns_a_timeout_into_a_skip,
    ),
]
