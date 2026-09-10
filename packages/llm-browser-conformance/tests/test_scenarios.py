"""Every scenario, for every requested driver, as one pytest case each."""

from llm_browser_conformance.runner import run_scenario
from llm_browser_conformance.scenario import Context, Scenario
from tests.support import check


def test_scenario(scenario: Scenario, ctx: Context) -> None:
    check(run_scenario(scenario, ctx))
