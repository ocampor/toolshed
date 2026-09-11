"""Synthetic scenarios that need no browser, one per verdict."""

from typing import cast

from llm_browser.session import BrowserSession

from llm_browser_conformance.scenario import (
    Context,
    Scenario,
    ScenarioSkipped,
    Section,
)

FAKE_DRIVER = "fake"


def passes(ctx: Context) -> None:
    return None


def notes(ctx: Context) -> str:
    return "observed something"


def fails(ctx: Context) -> None:
    raise AssertionError("boom")


def skips(ctx: Context) -> None:
    raise ScenarioSkipped("no api here")


FAKE_SCENARIOS = [
    Scenario("passes", Section.WAITS, passes),
    Scenario("notes", Section.WAITS, notes),
    Scenario("fails", Section.FLOWS, fails),
    Scenario("skips", Section.FLOWS, skips),
    Scenario(
        "known gap", Section.INPUTS, fails, known_gaps={FAKE_DRIVER: "documented"}
    ),
    Scenario(
        "gap closed", Section.INPUTS, passes, known_gaps={FAKE_DRIVER: "documented"}
    ),
    Scenario(
        "other driver only", Section.STEALTH, passes, drivers=frozenset({"other"})
    ),
]


def fake_context(driver: str = FAKE_DRIVER) -> Context:
    """No check here touches the session, so there is nothing to launch."""
    return Context(
        session=cast(BrowserSession, None),
        site_url="http://127.0.0.1:1",
        driver=driver,
    )
