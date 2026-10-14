"""Launched mode: Playwright's own ``Download`` events save the file locally."""

from collections.abc import Callable

from patchright.sync_api import Download, Page

from llm_browser.drivers.patchright_download import (
    Arrivals,
    Deadline,
    caught_file,
    poll_until,
    watching,
)
from llm_browser.drivers.playwright_base import read_download
from llm_browser.results import BytesResult


def catch_launched_download(
    page: Page, trigger: Callable[[], None], deadline: Deadline
) -> BytesResult:
    with watching(page, deadline, listen_for_launched_downloads) as arrivals:
        trigger()
        poll_until(page, arrivals, lambda: arrivals.downloads or None)
    if arrivals.downloads:
        return read_download(arrivals.downloads[0])
    return caught_file(arrivals)


def listen_for_launched_downloads(page: Page, arrivals: Arrivals) -> Callable[[], None]:
    # Closures, not bound methods: Playwright sets an attribute on each handler.
    def on_download(download: Download) -> None:
        arrivals.downloads.append(download)

    def on_popup(popup: Page) -> None:
        popup.on("download", on_download)

    page.on("download", on_download)
    page.on("popup", on_popup)

    def stop() -> None:
        page.remove_listener("download", on_download)
        page.remove_listener("popup", on_popup)

    return stop
