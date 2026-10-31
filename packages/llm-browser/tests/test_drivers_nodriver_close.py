# nodriver is not installed here; Browser.stop() is synchronous, so a FakeBrowser suffices.

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
    # Awaiting browser.stop() would raise TypeError; an open loop after close() shows it was not.
    browser = FakeBrowser()
    driver.browser = browser

    driver.close(HANDLE)

    assert browser.stop_calls == 1


def test_close_swallows_a_failing_stop(driver: NodriverDriver) -> None:
    # The CDP websocket may already be gone; a failing stop() must not skip resetting state.
    driver.browser = FakeBrowser(stop_error=RuntimeError("already disconnected"))

    driver.close(HANDLE)

    assert driver.browser is None
    assert driver.tab is None
    assert driver.loop is None


def test_close_drains_a_task_stop_left_pending_without_warning(
    driver: NodriverDriver,
) -> None:
    # Closing the loop under stop()'s pending disconnect task prints "Task was destroyed".
    browser = FakeBrowser(loop=driver.loop)
    driver.browser = browser

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        driver.close(HANDLE)

    runtime_warnings = [w for w in caught if issubclass(w.category, RuntimeWarning)]
    assert runtime_warnings == []
    assert browser.pending_task is not None
    assert browser.pending_task.cancelled()
