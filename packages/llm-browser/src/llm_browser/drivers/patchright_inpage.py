"""Downloads on an attached Chrome: it cannot write to Playwright's download
dir, so the bytes are read inside the page the download began in."""

import base64
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, TypedDict

from patchright.sync_api import Browser, CDPSession, Frame, Page

from llm_browser.constants import (
    DOWNLOAD_POLL_MS,
    DOWNLOAD_SLICE_BYTES,
    TRANSFER_EXCEEDED,
)
from llm_browser.drivers.patchright_download import Arrivals, Deadline, watch
from llm_browser.results import BytesResult, guess_media_type
from llm_browser.scripts import load_script


class DownloadBegin(TypedDict):
    """CDP ``Browser.downloadWillBegin``, the fields read here."""

    frameId: str
    url: str
    guid: str
    suggestedFilename: str


type OwnBegin = tuple[DownloadBegin, Frame]


def catch_in_page(
    browser: Browser, page: Page, trigger: Callable[[], None], deadline: Deadline
) -> BytesResult:
    arrivals = Arrivals(deadline)
    stop_watching = watch(page, arrivals)
    try:
        with download_events(browser) as (cdp, begins):
            keep_blobs(page)
            trigger()
            own, foreign = wait_for_begin(page, arrivals, begins)
            # Inside the try: the popup a download began in closes in the finally.
            if own is not None:
                return read_in_page(cdp, *own, deadline)
    finally:
        stop_watching()
    if arrivals.files:
        return arrivals.files[0]
    if foreign:
        raise ValueError("download started outside this tab")
    raise deadline.nothing_arrived()


@contextmanager
def download_events(
    browser: Browser,
) -> Iterator[tuple[CDPSession, list[DownloadBegin]]]:
    # Only the session that set the behavior receives downloadWillBegin, and
    # "deny" makes Chrome write nothing.
    # debt: another client's connect mid-step resets behavior and can steal events; the step then times out
    cdp = browser.new_browser_cdp_session()
    begins: list[DownloadBegin] = []

    def on_begin(event: DownloadBegin) -> None:
        begins.append(event)

    cdp.on("Browser.downloadWillBegin", on_begin)
    behavior = {"behavior": "deny", "eventsEnabled": True}
    try:
        cdp.send("Browser.setDownloadBehavior", behavior)
    except Exception as exc:
        with suppress(Exception):
            cdp.detach()
        raise ValueError(f"download did not complete: {brief(exc)}") from exc
    try:
        yield cdp, begins
    finally:
        with suppress(Exception):
            cdp.send("Browser.setDownloadBehavior", {"behavior": "default"})
        with suppress(Exception):
            cdp.detach()


def keep_blobs(page: Page) -> None:
    # Per step, not an init script: patchright routes the whole context for one.
    for frame in page.frames:
        with suppress(Exception):
            frame.evaluate(load_script("keep_blobs"), isolated_context=False)


def wait_for_begin(
    page: Page, arrivals: Arrivals, begins: list[DownloadBegin]
) -> tuple[OwnBegin | None, int]:
    """The first download begun in this tab, or None once a file arrives or
    time runs out; with how many begun elsewhere were skipped."""
    foreign = 0
    while arrivals.deadline.remaining_ms():
        if arrivals.files:
            return None, foreign
        while begins:
            begin = begins.pop(0)
            frame = frame_for([page, *arrivals.popups], begin["frameId"])
            if frame is not None:
                return (begin, frame), foreign
            foreign += 1
        page.wait_for_timeout(DOWNLOAD_POLL_MS)
    return None, foreign


def read_in_page(
    cdp: CDPSession, begin: DownloadBegin, frame: Frame, deadline: Deadline
) -> BytesResult:
    with suppress(Exception):
        cdp.send("Browser.cancelDownload", {"guid": begin["guid"]})
    try:
        content = read_bytes(frame, begin["url"], begin["guid"], deadline)
    except TimeoutError:
        raise
    except Exception as exc:
        raise ValueError(f"download did not complete: {brief(exc)}") from exc
    name = Path(begin["suggestedFilename"]).name
    return BytesResult(name=name, content=content, media_type=guess_media_type(name))


def read_bytes(frame: Frame, url: str, key: str, deadline: Deadline) -> bytes:
    # Main world: keep_blobs' kept Blobs and deferred revokes live there.
    read = [url, key, deadline.left_ms()]
    size = frame.evaluate(load_script("download_read"), read, isolated_context=False)
    if size < 0:
        raise TimeoutError(TRANSFER_EXCEEDED)
    chunks = []
    try:
        for start in range(0, size, DOWNLOAD_SLICE_BYTES):
            deadline.left_ms()
            span = [key, start, start + DOWNLOAD_SLICE_BYTES]
            chunk = frame.evaluate(
                load_script("download_slice"), span, isolated_context=False
            )
            chunks.append(base64.b64decode(chunk))
    finally:
        with suppress(Exception):
            frame.evaluate(load_script("download_drop"), key, isolated_context=False)
    return b"".join(chunks)


def brief(exc: Exception) -> str:
    return " ".join(str(exc).split())[:200]


def frame_for(pages: list[Page], frame_id: str) -> Frame | None:
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
    return None


def frame_tree(frame: Frame) -> dict[str, Any] | None:
    # Only a main frame or an out-of-process iframe owns a CDP session.
    try:
        session = frame.page.context.new_cdp_session(frame)
    except Exception:
        return None
    try:
        tree: dict[str, Any] = session.send("Page.getFrameTree")["frameTree"]
        return tree
    except Exception:
        return None
    finally:
        with suppress(Exception):
            session.detach()


def find_url(tree: dict[str, Any], frame_id: str) -> str | None:
    if tree["frame"]["id"] == frame_id:
        return str(tree["frame"]["url"])
    for child in tree.get("childFrames", []):
        url = find_url(child, frame_id)
        if url:
            return url
    return None
