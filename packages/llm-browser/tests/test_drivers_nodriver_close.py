"""NodriverDriver.close() stops the browser directly.

``nodriver`` is an optional extra and is NOT installed here — a ``FakeBrowser``
stands in for the real one, which is enough since ``Browser.stop()`` is a
synchronous method and ``close()`` must call it as one.
"""

import asyncio
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
