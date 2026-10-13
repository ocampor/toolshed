import base64
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from email.message import Message
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urlsplit

from patchright.sync_api import (
    Browser,
    CDPSession,
    Download,
    Frame,
    Page,
    Request,
    Route,
)

from llm_browser.constants import (
    DOWNLOAD_POLL_MS,
    DOWNLOAD_SLICE_BYTES,
    PAGE_MEDIA_TYPES,
)
from llm_browser.drivers.playwright_base import read_download
from llm_browser.results import BytesResult, guess_media_type
from llm_browser.scripts import load_script


class DownloadBegin(TypedDict):
    """CDP ``Browser.downloadWillBegin``, the fields read here."""

    frameId: str
    url: str
    guid: str
    suggestedFilename: str


@dataclass
class Arrivals:
    deadline: float
    downloads: list[Download] = field(default_factory=list)
    files: list[BytesResult] = field(default_factory=list)
    popups: list[Page] = field(default_factory=list)
    begins: list[DownloadBegin] = field(default_factory=list)
    foreign_begins: int = 0

    def remaining_ms(self) -> float:
        return max(0.0, (self.deadline - time.monotonic()) * 1000)


def catch_file(
    page: Page,
    trigger: Callable[[], None],
    timeout_ms: int,
    browser: Browser | None = None,
) -> BytesResult:
    """``browser`` is set when attached: the remote Chrome cannot write to
    Playwright's download dir, so the bytes are read inside the page."""
    arrivals = Arrivals(deadline=time.monotonic() + timeout_ms / 1000)
    stop_watching = watch(page, arrivals, listen_downloads=browser is None)
    cdp = None
    try:
        if browser is not None:
            cdp = watch_begins(browser, arrivals)
        trigger()
        own = wait_for_arrival(page, arrivals)
        # Inside the try: the popup a download began in closes in the finally.
        if cdp is not None and own is not None:
            return read_in_page(cdp, *own, arrivals.deadline)
    finally:
        if cdp is not None:
            stop_begins(cdp)
        stop_watching()
    if arrivals.downloads:
        return read_download(arrivals.downloads[0])
    if arrivals.files:
        return arrivals.files[0]
    if arrivals.foreign_begins:
        raise ValueError("download started outside this tab")
    raise TimeoutError(f"no file arrived within {timeout_ms}ms")


def wait_for_arrival(
    page: Page, arrivals: Arrivals
) -> tuple[DownloadBegin, Frame] | None:
    """The first download begun in this tab; None once anything else arrives."""
    while arrivals.remaining_ms():
        if arrivals.downloads or arrivals.files:
            return None
        while arrivals.begins:
            begin = arrivals.begins.pop(0)
            pages = [page, *arrivals.popups]
            frame = frame_for(pages, begin["frameId"], begin["url"])
            if frame is not None:
                return begin, frame
            arrivals.foreign_begins += 1
        page.wait_for_timeout(DOWNLOAD_POLL_MS)
    return None


def watch_begins(browser: Browser, arrivals: Arrivals) -> CDPSession:
    # Only the session that set the behavior receives downloadWillBegin, and
    # "deny" makes Chrome write nothing.
    # debt: another client's connect mid-step resets behavior and can steal events; the step then times out
    cdp = browser.new_browser_cdp_session()

    def on_begin(event: DownloadBegin) -> None:
        arrivals.begins.append(event)

    cdp.on("Browser.downloadWillBegin", on_begin)
    behavior = {"behavior": "deny", "eventsEnabled": True}
    cdp.send("Browser.setDownloadBehavior", behavior)
    return cdp


def stop_begins(cdp: CDPSession) -> None:
    with suppress(Exception):
        cdp.send("Browser.setDownloadBehavior", {"behavior": "default"})
    with suppress(Exception):
        cdp.detach()


def read_in_page(
    cdp: CDPSession, begin: DownloadBegin, frame: Frame, deadline: float
) -> BytesResult:
    with suppress(Exception):
        cdp.send("Browser.cancelDownload", {"guid": begin["guid"]})
    try:
        content = read_bytes(frame, begin["url"], begin["guid"], deadline)
    except TimeoutError:
        raise
    except Exception as exc:
        reason = " ".join(str(exc).split())[:200]
        raise ValueError(f"download did not complete: {reason}") from exc
    name = Path(begin["suggestedFilename"]).name
    return BytesResult(name=name, content=content, media_type=guess_media_type(name))


def read_bytes(frame: Frame, url: str, key: str, deadline: float) -> bytes:
    # Main world: the keep-blob init script's Blobs live there.
    size = frame.evaluate(
        load_script("download_read"), [url, key], isolated_context=False
    )
    chunks = []
    try:
        for start in range(0, size, DOWNLOAD_SLICE_BYTES):
            if time.monotonic() > deadline:
                raise TimeoutError("download transfer exceeded the step's timeout")
            span = [key, start, start + DOWNLOAD_SLICE_BYTES]
            chunk = frame.evaluate(
                load_script("download_slice"), span, isolated_context=False
            )
            chunks.append(base64.b64decode(chunk))
    finally:
        with suppress(Exception):
            frame.evaluate(load_script("download_drop"), key, isolated_context=False)
    return b"".join(chunks)


def frame_for(pages: list[Page], frame_id: str, url: str) -> Frame | None:
    """The frame of these tabs a download began in; None when it is not theirs."""
    frames = [frame for page in pages for frame in page.frames]
    for frame in frames:
        tree = frame_tree(frame)
        if tree is None:
            continue
        if tree["frame"]["id"] == frame_id:
            return frame
        # An in-process child frame has no session of its own; match it by url.
        child_url = find_url(tree, frame_id)
        same_url = [other for other in frames if other.url == child_url]
        if child_url and same_url:
            return same_url[0]
    origin = url_origin(url)
    return next((frame for frame in frames if url_origin(frame.url) == origin), None)


def frame_tree(frame: Frame) -> dict[str, Any] | None:
    # Only a main frame or an out-of-process iframe owns a CDP session.
    try:
        session = frame.page.context.new_cdp_session(frame)
    except Exception:
        return None
    try:
        tree: dict[str, Any] = session.send("Page.getFrameTree")["frameTree"]
        return tree
    finally:
        session.detach()


def find_url(tree: dict[str, Any], frame_id: str) -> str | None:
    if tree["frame"]["id"] == frame_id:
        return str(tree["frame"]["url"])
    for child in tree.get("childFrames", []):
        url = find_url(child, frame_id)
        if url:
            return url
    return None


def url_origin(url: str) -> tuple[str, str]:
    parts = urlsplit(url.removeprefix("blob:"))
    return parts.scheme, parts.netloc


def watch(page: Page, arrivals: Arrivals, listen_downloads: bool) -> Callable[[], None]:
    # Closures, not bound methods: Playwright sets an attribute on each handler.
    def on_download(download: Download) -> None:
        arrivals.downloads.append(download)

    def on_popup(popup: Page) -> None:
        arrivals.popups.append(popup)
        if listen_downloads:
            popup.on("download", on_download)

    def on_route(route: Route) -> None:
        intercept(route, page, arrivals)

    if listen_downloads:
        page.on("download", on_download)
    page.on("popup", on_popup)
    page.context.route("**/*", on_route)

    def stop() -> None:
        page.context.unroute("**/*", on_route)
        if listen_downloads:
            page.remove_listener("download", on_download)
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
        response = route.fetch(timeout=max(1.0, arrivals.remaining_ms()))
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
