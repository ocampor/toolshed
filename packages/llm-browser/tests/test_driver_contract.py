"""Rule 1 of the `Driver` contract, against every driver we can fake here.

The reads answer about the DOM as it is right now: a miss is 0 / False /
None / a locator that matches nothing, never a retry inside the driver and
never a raise. `llm_browser.waits` owns the deadline, and a read that blocked or
retried would make that deadline meaningless.
"""

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Iterator
from unittest.mock import MagicMock

import pytest

from llm_browser.drivers.base import Driver
from llm_browser.drivers.nodriver import NodriverDriver
from llm_browser.drivers.patchright import PatchrightDriver
from tests.driver_fakes import FakeTab

MISSING = "#missing"


@dataclass
class DriverCase:
    """A driver, a locator for a selector nothing matches, and the calls that
    would mean it waited."""

    driver: Driver
    locator: Any
    retrying_calls: Callable[[], list[Any]]


def nodriver_case() -> Iterator[DriverCase]:
    driver = NodriverDriver()
    driver.loop = asyncio.new_event_loop()
    tab = FakeTab([None])
    yield DriverCase(driver, driver.resolve(tab, MISSING), lambda: tab.select_all_calls)
    driver.loop.close()


def playwright_case() -> Iterator[DriverCase]:
    locator = MagicMock()
    locator.count.return_value = 0
    locator.is_visible.return_value = False
    # A locator for nothing narrows to itself, as Playwright's `.first` does.
    locator.first = locator
    page = MagicMock()
    page.locator.return_value = locator
    driver = PatchrightDriver()
    yield DriverCase(
        driver,
        driver.resolve(page, MISSING),
        lambda: locator.wait_for.mock_calls + locator.text_content.mock_calls,
    )


@pytest.fixture(params=[nodriver_case, playwright_case], ids=["nodriver", "patchright"])
def case(request: pytest.FixtureRequest) -> Iterator[DriverCase]:
    yield from request.param()


def test_count_of_a_missing_selector_is_zero(case: DriverCase) -> None:
    assert case.driver.count(case.locator) == 0


def test_the_reads_never_reach_a_retrying_api(case: DriverCase) -> None:
    case.driver.count(case.locator)
    case.driver.is_visible(case.driver.first(case.locator))
    case.driver.text_content(case.driver.first(case.locator))
    assert case.retrying_calls() == []


def test_is_visible_of_a_missing_selector_is_false(case: DriverCase) -> None:
    assert case.driver.is_visible(case.driver.first(case.locator)) is False


def test_text_content_of_a_missing_selector_is_none(case: DriverCase) -> None:
    assert case.driver.text_content(case.driver.first(case.locator)) is None


def test_first_of_a_missing_selector_does_not_raise(case: DriverCase) -> None:
    assert case.driver.first(case.locator) is not None
