"""Browser-free tests for the helpers the checks share.

The tab helpers are the reason this file exists: every driver installed today
implements ``latest_tab`` and closes its popups, so the paths that matter most
— no ``latest_tab`` at all, and a tab that never closes — are only reachable
with a fake session.
"""

import dataclasses
import itertools
import time
from collections.abc import Callable, Iterator
from typing import Any, cast

import pytest
from llm_browser.session import BrowserSession

from llm_browser_conformance.checks.session_api import (
    NEW_TAB_TARGET,
    close_opened_tabs,
    require_latest_tab,
    tabs_closed_after,
)
from llm_browser_conformance.scenario import Context, ScenarioSkipped
from tests.fakes import fake_context

# Enough iterations to prove the loop is spinning; the deadline should stop it
# long before this, and a RuntimeError rather than a hung suite says it did not.
RUNAWAY_CALLS = 1_000

OPENER = "the opener tab"


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


class SessionWhoseTabNeverCloses:
    """A session whose newest tab is a *different* object every time.

    That is the case the outer deadline exists for: ``close_tab``'s inner wait
    only runs while ``latest_tab()`` is the tab it just asked to close, so with
    a fresh object each call the inner deadline is never reached and only the
    outer one can end the loop.
    """

    def __init__(self) -> None:
        self.latest_tab_calls = 0

    def latest_tab(self) -> Any:
        self.latest_tab_calls += 1
        if self.latest_tab_calls > RUNAWAY_CALLS:
            raise RuntimeError("close_opened_tabs never gave up on the tab")
        return object()

    def evaluate(self, target: Any, expression: str) -> Any:
        """``close_opened_tabs`` polls for this url before it starts closing;
        answering it straight away keeps that timeout out of the test."""
        return f"http://127.0.0.1/{NEW_TAB_TARGET}"


def fake_clock(step: float = 1.0) -> Callable[[], float]:
    """A monotonic clock that advances a step per reading, so a deadline is
    reached in a handful of iterations and the test costs no wall time."""
    ticks = itertools.count(0.0, step)
    return lambda: next(ticks)


@pytest.fixture
def stuck_tab(monkeypatch: pytest.MonkeyPatch) -> Iterator[Context]:
    session = SessionWhoseTabNeverCloses()
    monkeypatch.setattr(time, "monotonic", fake_clock())
    yield context_for(session)


def test_a_tab_that_never_closes_gives_up_on_the_deadline(stuck_tab: Context) -> None:
    with pytest.raises(AssertionError, match="the opened tab never closed"):
        close_opened_tabs(stuck_tab, OPENER, NEW_TAB_TARGET)


def test_a_failing_cleanup_does_not_replace_the_scenario_failure(
    stuck_tab: Context,
) -> None:
    """Both go wrong at once: the scenario asserts and the popup then refuses
    to close. The table shows the newest exception, so the assertion has to be
    the one that comes out."""
    with (
        pytest.raises(AssertionError) as caught,
        tabs_closed_after(stuck_tab, OPENER, NEW_TAB_TARGET),
    ):
        raise AssertionError("new-tab.html not in current")

    assert str(caught.value) == "new-tab.html not in current"
    assert caught.value.__notes__ == ["cleanup failed too: the opened tab never closed"]


def test_a_failing_cleanup_is_raised_when_the_scenario_passed(
    stuck_tab: Context,
) -> None:
    with (
        pytest.raises(AssertionError, match="the opened tab never closed"),
        tabs_closed_after(stuck_tab, OPENER, NEW_TAB_TARGET),
    ):
        pass
