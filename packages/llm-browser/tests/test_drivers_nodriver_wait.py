"""NodriverDriver's DOM reads against hand-written async CDP doubles.

`nodriver` is an optional extra and is NOT installed here — these tests also
assert the wait paths never import it.
"""

import asyncio
import sys
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

from llm_browser.drivers.nodriver import NodriverDriver, NodriverLocator
from llm_browser.models import WaitState
from llm_browser.session import BrowserSession

POLL_MS = 1


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
        self.select_all_calls: list[str] = []
        self.query_calls: list[str] = []

    async def query_selector_all(self, selector: str) -> list[Any]:
        self.query_calls.append(selector)
        found = self.next_result()
        if found is None:
            return []
        return found if isinstance(found, list) else [found]

    async def select_all(self, selector: str, timeout: float = 10) -> list[Any]:
        """Real nodriver retries in here — 500ms and a `Target.getTargets` per
        cycle — so no read on the wait path may reach this method at all."""
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


# --- count: one bare query, no retry, no cache ---


def test_count_never_reaches_the_retrying_query(driver: NodriverDriver) -> None:
    loc = _locator([None])

    assert driver.count(loc) == 0
    assert loc.tab.select_all_calls == []
    assert loc.tab.query_calls == ["#out"]


def test_count_re_queries_instead_of_reading_a_cache(driver: NodriverDriver) -> None:
    loc = _locator([FakeElement(True), None])
    assert driver.count(loc) == 1

    assert driver.count(loc) == 0


def test_count_reads_the_handle_without_a_selector(driver: NodriverDriver) -> None:
    loc = _locator([FakeElement(True)], selector=None)

    assert driver.count(loc) == 1
    assert loc.tab.query_calls == []


# --- is_visible: a single read of the element as it is now ---


def test_is_visible_is_false_for_a_missing_selector(driver: NodriverDriver) -> None:
    assert driver.is_visible(_locator([None])) is False


def test_is_visible_is_false_once_a_stale_handle_stops_answering(
    driver: NodriverDriver,
) -> None:
    assert driver.is_visible(_locator([DetachedElement()], selector=None)) is False


def test_first_stays_lazy_so_the_selector_survives(driver: NodriverDriver) -> None:
    parent = NodriverLocator(tab=FakeTab([None]), selector="#out")
    assert driver.first(parent).selector == "#out"


def test_nth_keeps_the_selector_and_reads_its_own_index(
    driver: NodriverDriver,
) -> None:
    shown, hidden = FakeElement(True), FakeElement(False)
    parent = NodriverLocator(tab=FakeTab([[shown, hidden]]), selector="li")

    item = driver.nth(parent, 1)

    assert (item.selector, item.index, item.element) == ("li", 1, hidden)
    assert driver.is_visible(item) is False


# --- session -> nodriver seam: no mock driver, the real NodriverDriver ---


@pytest.fixture
def session(driver: NodriverDriver, tmp_path: Path) -> Callable[[list[Any]], Any]:
    def open_on(results: list[Any]) -> BrowserSession:
        s = BrowserSession(state_dir=tmp_path, driver=driver)
        s._page = FakeTab(results)
        return s

    return open_on


def _wait(session: BrowserSession, state: WaitState, timeout: int = 500) -> None:
    session.wait_for_element("#out", state=state, timeout=timeout, interval=POLL_MS)


def test_wait_paths_never_import_nodriver(
    session: Callable[[list[Any]], BrowserSession],
) -> None:
    states: list[WaitState] = ["attached", "detached", "visible", "hidden"]
    for state in states:
        try:
            _wait(session([FakeElement(True)]), state, timeout=20)
        except TimeoutError:
            pass
    assert sys.modules.get("nodriver") is None


def test_detached_times_out_while_the_element_stays(
    session: Callable[[list[Any]], BrowserSession],
) -> None:
    with pytest.raises(TimeoutError, match="#out did not become detached"):
        _wait(session([FakeElement(True)]), "detached", timeout=20)


def test_detached_returns_once_the_node_is_removed(
    session: Callable[[list[Any]], BrowserSession],
) -> None:
    _wait(session([FakeElement(True), None]), "detached")


def test_hidden_returns_once_the_node_is_removed(
    session: Callable[[list[Any]], BrowserSession],
) -> None:
    _wait(session([FakeElement(True), None]), "hidden")


def test_visible_returns_after_the_node_is_replaced(
    session: Callable[[list[Any]], BrowserSession],
) -> None:
    _wait(session([FakeElement(False), FakeElement(True)]), "visible")


def test_a_wait_never_reaches_the_retrying_query(
    session: Callable[[list[Any]], BrowserSession],
) -> None:
    s = session([None])
    with pytest.raises(TimeoutError):
        _wait(s, "attached", timeout=20)
    assert s._page.select_all_calls == []


def test_element_exists_is_false_for_a_missing_selector(
    session: Callable[[list[Any]], BrowserSession],
) -> None:
    assert session([None]).element_exists("#missing", 40) is False
