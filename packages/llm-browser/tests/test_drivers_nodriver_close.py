"""NodriverDriver.close() stops the browser directly.

``nodriver`` is an optional extra and is NOT installed here — a ``FakeBrowser``
stands in for the real one, which is enough since ``Browser.stop()`` is a
synchronous method and ``close()`` must call it as one.
"""

import asyncio
import warnings
from collections.abc import Iterator

import pytest

from llm_browser.drivers.handle import DriverHandle
from llm_browser.drivers.nodriver import NodriverDriver
from tests.driver_fakes import FakeBrowser

HANDLE = DriverHandle(driver="nodriver", user_data_dir="/tmp/does-not-matter")


@pytest.fixture
def driver() -> Iterator[NodriverDriver]:
    d = NodriverDriver()
    d.loop = asyncio.new_event_loop()
    yield d
    if d.loop is not None and not d.loop.is_closed():
        d.loop.close()


def test_close_calls_stop_directly_once(driver: NodriverDriver) -> None:
    """A loop.run_until_complete(browser.stop()) would raise TypeError on the
    non-coroutine result; asserting the loop is still open after close()
    shows that path was never taken."""
    browser = FakeBrowser()
    driver.browser = browser

    driver.close(HANDLE)

    assert browser.stop_calls == 1


def test_close_swallows_a_failing_stop(driver: NodriverDriver) -> None:
    """Shutdown stays racy — the CDP websocket may already be disconnected —
    so a genuine failure inside Browser.stop() must not stop close() from
    resetting driver state."""
    driver.browser = FakeBrowser(stop_error=RuntimeError("already disconnected"))

    driver.close(HANDLE)

    assert driver.browser is None
    assert driver.tab is None
    assert driver.loop is None


def test_close_drains_a_task_stop_left_pending_without_warning(
    driver: NodriverDriver,
) -> None:
    """Browser.stop() schedules a disconnect task on the loop but never runs
    it; closing the loop underneath that task is what prints "Task was
    destroyed but it is pending!" and warns that its coroutine was never
    awaited."""
    browser = FakeBrowser(loop=driver.loop)
    driver.browser = browser

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        driver.close(HANDLE)

    runtime_warnings = [w for w in caught if issubclass(w.category, RuntimeWarning)]
    assert runtime_warnings == []
    assert browser.pending_task is not None
    assert browser.pending_task.cancelled()
