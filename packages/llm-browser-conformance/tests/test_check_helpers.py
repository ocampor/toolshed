"""Browser-free tests for the helpers the checks share.

Every driver installed today implements ``latest_tab``, so the path where one
does not is only reachable from here.
"""

import dataclasses
from typing import Any, cast

import pytest
from llm_browser.session import BrowserSession

from llm_browser_conformance.checks.session_api import require_latest_tab
from llm_browser_conformance.scenario import Context, ScenarioSkipped
from tests.fakes import fake_context


class SessionWithoutLatestTab:
    def latest_tab(self) -> Any:
        raise NotImplementedError("FakeDriver does not support latest_tab")


class SessionWithLatestTab:
    def latest_tab(self) -> Any:
        return object()


def context_for(session: object) -> Context:
    return dataclasses.replace(fake_context(), session=cast(BrowserSession, session))


def test_a_driver_without_latest_tab_skips_before_a_tab_is_opened() -> None:
    with pytest.raises(ScenarioSkipped, match="does not support latest_tab"):
        require_latest_tab(context_for(SessionWithoutLatestTab()))


def test_a_driver_with_latest_tab_runs_the_scenario() -> None:
    require_latest_tab(context_for(SessionWithLatestTab()))
