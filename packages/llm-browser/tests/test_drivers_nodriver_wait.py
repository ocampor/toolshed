"""NodriverDriver.wait_for_state against hand-written async CDP doubles.

`nodriver` is an optional extra and is NOT installed here — these tests also
assert the wait paths never import it.
"""

import asyncio
import sys
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

from llm_browser.drivers.nodriver import NodriverDriver, NodriverLocator
from llm_browser.session import BrowserSession


class FakeElement:
    def __init__(self, visible: bool) -> None:
        self.visible = visible

    async def apply(self, script: str) -> bool:
        return self.visible


class DetachedElement:
    """A handle whose node the page already removed: CDP reads on it fail."""

    async def apply(self, script: str) -> bool:
        raise RuntimeError("Could not find node with given id")


class FakeTab:
    """Serves each queued query result in turn, repeating the last one."""

    def __init__(self, results: list[Any]) -> None:
        self.results = results
        self.wait_for_calls: list[tuple[str, float]] = []
        self.select_all_calls: list[str] = []
        self.query_calls: list[str] = []

    async def wait_for(self, selector: str, timeout: float) -> None:
        self.wait_for_calls.append((selector, timeout))
        if self.next_result() is None:
            raise TimeoutError(selector)

    async def query_selector_all(self, selector: str) -> list[Any]:
        self.query_calls.append(selector)
        found = self.next_result()
        if found is None:
            return []
        return found if isinstance(found, list) else [found]

    async def select_all(self, selector: str, timeout: float = 10) -> list[Any]:
        """Real nodriver retries in here — 500ms and a `Target.getTargets` per
        cycle — so a poll tick must not reach this method at all."""
        self.select_all_calls.append(selector)
        return await self.query_selector_all(selector)

    def next_result(self) -> Any:
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


def test_detached_times_out_for_element_locator_without_selector(
    driver: NodriverDriver,
) -> None:
    """Without a selector there is nothing to re-query, so "gone" is never
    observable — timing out is the honest answer, not an instant success."""
    loc = _locator([FakeElement(True)], selector=None)
    with pytest.raises(TimeoutError, match="element detached"):
        driver.wait_for_state(loc, "detached", 20)


def test_hidden_succeeds_once_a_stale_handle_stops_answering(
    driver: NodriverDriver,
) -> None:
    loc = _locator([DetachedElement()], selector=None)
    driver.wait_for_state(loc, "hidden", 20)


def test_nth_keeps_the_selector_and_polls_its_own_index(
    driver: NodriverDriver,
) -> None:
    shown, hidden = FakeElement(True), FakeElement(False)
    parent = NodriverLocator(tab=FakeTab([[shown, hidden]]), selector="li")
    item = driver.nth(parent, 1)
    assert (item.selector, item.index, item.element) == ("li", 1, hidden)
    with pytest.raises(TimeoutError, match="visible"):
        driver.wait_for_state(item, "visible", 20)


def test_first_stays_lazy_so_the_selector_survives(driver: NodriverDriver) -> None:
    parent = NodriverLocator(tab=FakeTab([None]), selector="#out")
    assert driver.first(parent).selector == "#out"


def test_wait_paths_never_import_nodriver(driver: NodriverDriver) -> None:
    for state in ("attached", "detached", "visible", "hidden"):
        loc = _locator([None])
        try:
            driver.wait_for_state(loc, state, 20)
        except TimeoutError:
            pass
    assert sys.modules.get("nodriver") is None


# --- session -> nodriver seam: no mock driver, the real NodriverDriver ---


@pytest.fixture
def session(driver: NodriverDriver, tmp_path: Path) -> Callable[[list[Any]], Any]:
    def open_on(results: list[Any]) -> BrowserSession:
        s = BrowserSession(state_dir=tmp_path, driver=driver)
        s._page = FakeTab(results)
        return s

    return open_on


def test_wait_for_detached_is_false_while_the_element_stays(
    session: Callable[[list[Any]], BrowserSession],
) -> None:
    assert session([FakeElement(True)]).wait_for("#out", "detached", 40) is False


def test_wait_for_detached_is_true_once_the_node_is_removed(
    session: Callable[[list[Any]], BrowserSession],
) -> None:
    assert session([FakeElement(True), None]).wait_for("#out", "detached", 500) is True


def test_wait_for_hidden_is_true_once_the_node_is_removed(
    session: Callable[[list[Any]], BrowserSession],
) -> None:
    assert session([FakeElement(True), None]).wait_for("#out", "hidden", 500) is True


def test_wait_for_visible_is_true_after_the_node_is_replaced(
    session: Callable[[list[Any]], BrowserSession],
) -> None:
    replacement = FakeElement(True)
    assert session([FakeElement(False), replacement]).wait_for("#out", "visible", 500)


def test_element_exists_is_false_for_a_missing_selector(
    session: Callable[[list[Any]], BrowserSession],
) -> None:
    assert session([None]).element_exists("#missing", 40) is False


def test_count_now_never_reaches_the_retrying_query(driver: NodriverDriver) -> None:
    loc = _locator([None])

    assert driver.count_now(loc) == 0
    assert loc.tab.select_all_calls == []
    assert loc.tab.query_calls == ["#out"]


def test_count_keeps_its_waiting_semantics(driver: NodriverDriver) -> None:
    loc = _locator([FakeElement(True)])

    assert driver.count(loc) == 1
    assert loc.tab.select_all_calls == ["#out"]


def test_count_now_re_queries_instead_of_reading_the_cache(
    driver: NodriverDriver,
) -> None:
    loc = _locator([FakeElement(True), None])
    assert driver.count(loc) == 1

    assert driver.count_now(loc) == 0


def test_count_now_falls_back_without_a_selector(driver: NodriverDriver) -> None:
    loc = _locator([FakeElement(True)], selector=None)

    assert driver.count_now(loc) == 1
    assert loc.tab.query_calls == []
