"""Real-browser conformance suite for llm-browser drivers.

The scenarios live in :mod:`llm_browser_conformance.scenarios`; run them with
``llm-browser-check`` or through the pytest wrapper in this package's
``tests/``.
"""

from llm_browser_conformance.scenario import Outcome, Scenario, ScenarioSkipped
from llm_browser_conformance.scenarios import ALL_SCENARIOS

__all__ = ["ALL_SCENARIOS", "Outcome", "Scenario", "ScenarioSkipped"]
