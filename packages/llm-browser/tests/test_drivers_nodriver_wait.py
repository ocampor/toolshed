"""NodriverDriver.wait_for_state against hand-written async CDP doubles.

`nodriver` is an optional extra and is NOT installed here — these tests also
assert the wait paths never import it.
"""

import asyncio
import sys
from typing import Any, Iterator

import pytest

from llm_browser.drivers.nodriver import NodriverDriver, NodriverLocator


class FakeElement:
    def __init__(self, visible: bool) -> None:
        self.visible = visible

    async def apply(self, script: str) -> bool:
        return self.visible


class FakeTab:
    """`query_selector` returns each queued result in turn, repeating the last."""

    def __init__(self, results: list[Any]) -> None:
        self.results = results
        self.wait_for_calls: list[tuple[str, float]] = []

    async def wait_for(self, selector: str, timeout: float) -> None:
        self.wait_for_calls.append((selector, timeout))

    async def query_selector(self, selector: str) -> Any:
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


@pytest.fixture
def driver() -> Iterator[NodriverDriver]:
    d = NodriverDriver()
    d.loop = asyncio.new_event_loop()
    yield d
    d.loop.close()


def _locator(results: list[Any], selector: str | None = "#out") -> NodriverLocator:
    tab = FakeTab(results)
    element = None if selector is not None else results[0]
    return NodriverLocator(tab=tab, selector=selector, element=element)


def test_attached_delegates_to_tab_wait_for(driver: NodriverDriver) -> None:
    loc = _locator([FakeElement(True)])
    driver.wait_for_state(loc, "attached", 50)
    assert loc.tab.wait_for_calls == [("#out", 0.05)]


def test_detached_succeeds_once_element_disappears(driver: NodriverDriver) -> None:
    loc = _locator([FakeElement(True), None])
    driver.wait_for_state(loc, "detached", 500)


def test_detached_times_out_while_element_stays(driver: NodriverDriver) -> None:
    loc = _locator([FakeElement(True)])
    with pytest.raises(TimeoutError, match="detached"):
        driver.wait_for_state(loc, "detached", 20)


def test_visible_succeeds_once_element_reports_visible(driver: NodriverDriver) -> None:
    loc = _locator([None, FakeElement(True)])
    driver.wait_for_state(loc, "visible", 500)


def test_visible_times_out_while_element_is_not_rendered(
    driver: NodriverDriver,
) -> None:
    loc = _locator([FakeElement(False)])
    with pytest.raises(TimeoutError, match="visible"):
        driver.wait_for_state(loc, "visible", 20)


def test_hidden_succeeds_when_element_is_not_rendered(driver: NodriverDriver) -> None:
    loc = _locator([FakeElement(False)])
    driver.wait_for_state(loc, "hidden", 20)


def test_hidden_succeeds_for_element_locator_without_selector(
    driver: NodriverDriver,
) -> None:
    loc = _locator([FakeElement(False)], selector=None)
    driver.wait_for_state(loc, "hidden", 20)


def test_detached_is_a_noop_for_element_locator_without_selector(
    driver: NodriverDriver,
) -> None:
    loc = _locator([FakeElement(True)], selector=None)
    driver.wait_for_state(loc, "detached", 20)


def test_wait_paths_never_import_nodriver(driver: NodriverDriver) -> None:
    for state in ("attached", "detached", "visible", "hidden"):
        loc = _locator([None])
        try:
            driver.wait_for_state(loc, state, 20)
        except TimeoutError:
            pass
    assert sys.modules.get("nodriver") is None
