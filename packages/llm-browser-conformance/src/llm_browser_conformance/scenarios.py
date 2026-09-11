"""The scenario list: everything the suite knows how to check.

One flat, declarative sequence, assembled from the ``checks`` modules so each
group stays readable on its own. Both front ends walk this list — adding a
scenario here adds a row to ``llm-browser-check`` and a pytest case at once.
"""

from llm_browser_conformance.checks import (
    controls,
    flows,
    frames,
    inputs,
    options,
    results,
    session_api,
    stealth,
    step_types,
    steps,
    waits,
)
from llm_browser_conformance.scenario import Scenario

ALL_SCENARIOS: list[Scenario] = [
    *waits.SCENARIOS,
    *flows.SCENARIOS,
    *inputs.SCENARIOS,
    *frames.SCENARIOS,
    *steps.SCENARIOS,
    *controls.SCENARIOS,
    *step_types.SCENARIOS,
    *options.SCENARIOS,
    *results.SCENARIOS,
    *session_api.SCENARIOS,
    *stealth.SCENARIOS,
]


def select(names: tuple[str, ...] = ()) -> list[Scenario]:
    """``names`` filters by substring, so ``--only wait`` picks the wait rows."""
    if not names:
        return ALL_SCENARIOS
    return [s for s in ALL_SCENARIOS if any(name in s.name for name in names)]
