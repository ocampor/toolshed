"""Turn a downloaded file into the pages a ``download`` step's ``extract:``
asks for. Only requested pages are read or rendered, so a huge PDF costs
what the budget lets through."""

import codecs
import hashlib
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from llm_browser.constants import EXTRACT_PAGE_OVERHEAD_CHARS, MISSING_DOCUMENTS_EXTRA
from llm_browser.download_extract import (
    Extract,
    ImageExtract,
    TextExtract,
    format_pages,
    select_pages,
)
from llm_browser.page_images import Frame, image_frame, open_image, shrink
from llm_browser.results import BytesResult, DocumentResult, ImagePage, TextPage

if TYPE_CHECKING:
    import pypdfium2
    from PIL.Image import Image

# debt: process-wide pdfium lock; pdfium is not thread-safe
PDFIUM_LOCK = threading.Lock()


@dataclass
class PageBatch:
    page_count: int | None
    pages: list[TextPage | ImagePage]
    rest: list[int]


@dataclass
class Pdf:
    document: "pypdfium2.PdfDocument"


@dataclass
class Picture:
    image: "Image"


@dataclass
class Text:
    text: str


type Source = Pdf | Picture | Text | None


def extract_file(file: BytesResult, spec: Extract) -> DocumentResult:
    require_documents_extra()
    with sniffed(file.content) as source:
        unreadable = source is None or isinstance(source, Text)
        labelled_image = file.media_type.startswith("image/")
        if isinstance(spec, ImageExtract) and labelled_image and unreadable:
            raise ValueError(f"{file.media_type} file is not a readable image")
        batch = read_pages(source, spec)
    return DocumentResult(
        filename=file.name,
        content_type=file.media_type,
        size=len(file.content),
        sha256=hashlib.sha256(file.content).hexdigest(),
        mode=spec.mode,
        page_count=batch.page_count,
        truncated=bool(batch.rest) or any(map(is_clipped, batch.pages)),
        next_pages=format_pages(batch.rest) or None,
        pages=batch.pages,
    )


def read_pages(source: Source, spec: Extract) -> PageBatch:
    """An empty batch when the file has nothing ``spec.mode`` reads."""
    match source, spec:
        case Pdf(pdf), TextExtract():
            return take_text(len(pdf), partial(pdf_text, pdf), spec)
        case Text(text), TextExtract():
            size = max(spec.max_chars - EXTRACT_PAGE_OVERHEAD_CHARS, 1)
            chunks = [text[i : i + size] for i in range(0, len(text), size)]
            return take_text(len(chunks), lambda page: chunks[page - 1], spec)
        case Pdf(pdf), ImageExtract():
            return take_images(len(pdf), partial(pdf_frame, pdf, spec), spec)
        case Picture(image), ImageExtract():
            try:
                frame_count: int = getattr(image, "n_frames", 1)
                frame = partial(image_frame, image, spec)
                return take_images(frame_count, frame, spec)
            except ValueError:
                raise
            # Untrusted parse: Pillow raises OSError, EOFError, struct.error, SyntaxError...
            except Exception as exc:
                raise ValueError(f"not a readable image: {exc!r}") from exc
    return PageBatch(page_count=None, pages=[], rest=[])


@contextmanager
def sniffed(content: bytes) -> Iterator[Source]:
    """By content, not media type, since servers mislabel downloads; closes
    what it opened, so a long-lived server leaks no pdfium handle."""
    if content.startswith(b"%PDF"):
        with PDFIUM_LOCK, opened_pdf(content) as pdf:
            yield Pdf(pdf)
        return
    image = open_image(content)
    if image is not None:
        with image:
            yield Picture(image)
        return
    text = decode_text(content)
    yield None if text is None else Text(text)


def is_clipped(page: TextPage | ImagePage) -> bool:
    return isinstance(page, TextPage) and page.clipped


def require_documents_extra() -> None:
    try:
        import PIL  # noqa: F401
        import pillow_heif  # noqa: F401
        import pypdfium2  # noqa: F401
    except ImportError as exc:
        raise ValueError(MISSING_DOCUMENTS_EXTRA) from exc


# --- budgets ---


def take_text(
    page_count: int, page_text: Callable[[int], str], spec: TextExtract
) -> PageBatch:
    """``max_chars`` is a hard ceiling and every page, blank or not, costs
    ``EXTRACT_PAGE_OVERHEAD_CHARS`` of it: a first page longer than what is
    left is clipped, and a later page that does not fit is left for
    ``next_pages``."""
    selected = select_pages(spec.pages, page_count)
    pages: list[TextPage | ImagePage] = []
    used = 0
    for i, page in enumerate(selected):
        text = page_text(page)
        room = spec.max_chars - used - EXTRACT_PAGE_OVERHEAD_CHARS
        if len(text) <= room:
            pages.append(TextPage(page=page, text=text))
            used += EXTRACT_PAGE_OVERHEAD_CHARS + len(text)
        elif pages:
            return PageBatch(page_count, pages, rest=selected[i:])
        else:
            kept = text[: max(room, 0)]
            clipped = TextPage(page=page, text=kept, clipped=True)
            rest = selected[i + 1 :]
            return PageBatch(page_count, [clipped], rest)
    return PageBatch(page_count, pages, rest=[])


def take_images(
    page_count: int, frame: Callable[[int], Frame], spec: ImageExtract
) -> PageBatch:
    selected = select_pages(spec.pages, page_count)
    shown = selected[: spec.max_images]
    pages: list[TextPage | ImagePage] = [
        shrink(page, frame(page), spec) for page in shown
    ]
    return PageBatch(page_count, pages, rest=selected[spec.max_images :])


# --- PDF ---


@contextmanager
def opened_pdf(content: bytes) -> Iterator["pypdfium2.PdfDocument"]:
    import pypdfium2

    try:
        pdf = pypdfium2.PdfDocument(content)
    except pypdfium2.PdfiumError as exc:
        raise ValueError(f"not a readable PDF: {exc}") from exc
    try:
        yield pdf
    finally:
        pdf.close()


@contextmanager
def page_errors(page: int) -> Iterator[None]:
    """pdfium can fail on one page of a file it opened; that is a step failure."""
    import pypdfium2

    try:
        yield
    except pypdfium2.PdfiumError as exc:
        raise ValueError(f"page {page} unreadable: {exc}") from exc


def pdf_text(pdf: "pypdfium2.PdfDocument", page: int) -> str:
    with page_errors(page):
        text: str = pdf[page - 1].get_textpage().get_text_bounded()
    return text


def pdf_frame(pdf: "pypdfium2.PdfDocument", spec: ImageExtract, page: int) -> Frame:
    """Rendered with the long side at ``max_long_side``, since PDF points are
    too coarse to read at 1:1; the original size is in points."""
    with page_errors(page):
        pdf_page = pdf[page - 1]
        width, height = pdf_page.get_size()
        scale = spec.max_long_side / max(width, height)
        image: Image = pdf_page.render(scale=scale).to_pil()
    return Frame(image, round(width), round(height))


# --- plain text ---


def decode_text(content: bytes) -> str | None:
    if content.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return decoded(content, "utf-16")
    if b"\x00" in content:
        return None
    return decoded(content, "utf-8-sig") or decoded(content, "cp1252")


def decoded(content: bytes, encoding: str) -> str | None:
    try:
        return content.decode(encoding)
    except UnicodeDecodeError:
        return None
