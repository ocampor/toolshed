"""Flow-level conformance: what a caller gets back when a step fails.

The library's promise is that a failed step is a value, not an exception, and
that the value carries enough to retry or hand to a human — so these check the
artifacts on disk and the ``human_needed`` verdict, not just the failure.
"""

from pathlib import Path

from llm_browser.flows import run_flow
from llm_browser.models import FlowError, FlowSuccess

from llm_browser_conformance.scenario import Context, Scenario, Section


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


def an_optional_wait_step_turns_a_timeout_into_a_skip(ctx: Context) -> None:
    ctx.visit("never.html")
    result = run_flow(ctx.session, ctx.flow("wait-never-optional"), {})
    assert isinstance(result, FlowSuccess), result


SCENARIOS = [
    Scenario(
        "flow failure captures artifacts",
        Section.FLOWS,
        a_failing_wait_step_captures_screenshot_and_dom,
        "never.html",
    ),
    Scenario(
        "flow failure flags a login wall",
        Section.FLOWS,
        a_failure_behind_a_login_wall_asks_for_a_human,
        "login-wall.html",
        known_gaps={
            "nodriver": "page_probe.js is a function literal and nodriver's "
            "evaluate runs it as an expression, so PageProbe comes back empty "
            "and human_needed is always False"
        },
    ),
    Scenario(
        "optional step swallows a timeout",
        Section.FLOWS,
        an_optional_wait_step_turns_a_timeout_into_a_skip,
        "never.html",
    ),
]
