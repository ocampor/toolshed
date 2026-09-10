"""Every scenario, for every requested driver, as one pytest case each."""

import pytest

from llm_browser_conformance.scenario import Context, Scenario, ScenarioSkipped


def test_scenario(
    scenario: Scenario, ctx: Context, request: pytest.FixtureRequest
) -> None:
    if not scenario.applies_to(ctx.driver):
        pytest.skip(f"{scenario.name} does not apply to {ctx.driver}")
    gap = scenario.gap_for(ctx.driver)
    if gap:
        # strict: a gap that has closed must show up as a failure, so the
        # known-gaps table in the README cannot quietly go stale.
        request.node.add_marker(pytest.mark.xfail(reason=gap, strict=True))
    try:
        scenario.check(ctx)
    except ScenarioSkipped as skipped:
        pytest.skip(str(skipped))
