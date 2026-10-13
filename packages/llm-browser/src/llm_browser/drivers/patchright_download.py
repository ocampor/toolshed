import time
from collections.abc import Callable
from dataclasses import dataclass, field
from email.message import Message
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

from patchright.sync_api import Download, Page, Request, Route

from llm_browser.constants import (
    DOWNLOAD_POLL_MS,
    PAGE_MEDIA_TYPES,
    TRANSFER_EXCEEDED,
)
from llm_browser.drivers.playwright_base import read_download
from llm_browser.results import BytesResult

@dataclass(frozen=True)
class Deadline:
    """One budget for a download step: the wait for a file and its transfer."""

    at: float
    timeout_ms: int

    @classmethod
    def start(cls, timeout_ms: int) -> Self:
        return cls(at=time.monotonic() + timeout_ms / 1000, timeout_ms=timeout_ms)

    def remaining_ms(self) -> float:
        return max(0.0, (self.at - time.monotonic()) * 1000)

    def left_ms(self) -> int:
        left = int((self.at - time.monotonic()) * 1000)
        if left <= 0:
            raise TimeoutError(TRANSFER_EXCEEDED)
        return left

    def nothing_arrived(self) -> TimeoutError:
        return TimeoutError(f"no file arrived within {self.timeout_ms}ms")


@dataclass
class Arrivals:
    deadline: Deadline
    downloads: list[Download] = field(default_factory=list)
    files: list[BytesResult] = field(default_factory=list)
    popups: list[Page] = field(default_factory=list)


def catch_download(
    page: Page, trigger: Callable[[], None], deadline: Deadline
) -> BytesResult:
    arrivals = Arrivals(deadline)
    stop_listening = listen_for_downloads(page, arrivals)
    stop_watching = watch(page, arrivals, after_unroute=stop_listening)
    try:
        trigger()
        while not (arrivals.downloads or arrivals.files) and deadline.remaining_ms():
            page.wait_for_timeout(DOWNLOAD_POLL_MS)
    finally:
        stop_watching()
    if arrivals.downloads:
        return read_download(arrivals.downloads[0])
    if arrivals.files:
        return arrivals.files[0]
    raise deadline.nothing_arrived()


def listen_for_downloads(page: Page, arrivals: Arrivals) -> Callable[[], None]:
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


def watch(
    page: Page, arrivals: Arrivals, after_unroute: Callable[[], None] = lambda: None
) -> Callable[[], None]:
    """Stopping closes the popups. ``after_unroute`` runs once the route is
    gone, so events queued during the unroute round trip still land."""

    def on_popup(popup: Page) -> None:
        arrivals.popups.append(popup)

    def on_route(route: Route) -> None:
        intercept(route, page, arrivals)

    page.on("popup", on_popup)
    page.context.route("**/*", on_route)

    def stop() -> None:
        page.context.unroute("**/*", on_route)
        after_unroute()
        page.remove_listener("popup", on_popup)
        for popup in arrivals.popups:
            popup.close()

    return stop


def intercept(route: Route, page: Page, arrivals: Arrivals) -> None:
    if not is_own_navigation(route.request, page, arrivals.popups):
        route.continue_()
        return
    # A fetch that outlives the step's budget hands the request back, so a real
    # download still reaches the browser rather than the route hanging it.
    # Playwright reads a 0 timeout as "none", hence the floor.
    try:
        response = route.fetch(timeout=max(1.0, arrivals.deadline.remaining_ms()))
    except Exception:
        route.continue_()
        return
    content_type = response.headers.get("content-type", "")
    media_type = content_type.split(";")[0].strip().lower()
    if media_type and media_type not in PAGE_MEDIA_TYPES:
        disposition = response.headers.get("content-disposition", "")
        name = file_name(disposition, response.url)
        arrivals.files.append(
            BytesResult(name=name, content=response.body(), media_type=media_type)
        )
    route.fulfill(response=response)


def is_own_navigation(request: Request, page: Page, popups: list[Page]) -> bool:
    if not request.is_navigation_request():
        return False
    # A popup's first navigation has no frame yet: it is the tab the click opened.
    # debt: another run's tab opened in that same instant would be taken as ours.
    try:
        frame = request.frame
    except Exception:
        return True
    return frame.parent_frame is None and (frame.page == page or frame.page in popups)


def file_name(content_disposition: str, url: str) -> str:
    header = Message()
    header["content-disposition"] = content_disposition
    name = header.get_filename() or Path(urlsplit(url).path).name
    return Path(name).name
