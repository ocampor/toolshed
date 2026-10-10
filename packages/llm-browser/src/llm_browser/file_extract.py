"""Turn a downloaded file into the pages a ``download`` step's ``extract:``
asks for. Only requested pages are read or rendered, so a huge PDF costs
what the budget lets through."""

import hashlib
import io
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from llm_browser.constants import MISSING_DOCUMENTS_EXTRA
from llm_browser.download_extract import Extract, ImageExtract, TextExtract, page_ranges
from llm_browser.results import BytesResult, DocumentResult, ImagePage, TextPage

if TYPE_CHECKING:
    import pypdfium2
    from PIL.Image import Image

# A page as pixels, with the size it had before any shrinking.
type Frame = tuple["Image", tuple[int, int]]


@dataclass
class Budgeted:
    pages: list[TextPage | ImagePage]
    rest: list[int]
    clipped: bool = False


def extract_file(file: BytesResult, spec: Extract) -> DocumentResult:
    require_documents_extra()
    content = file.content
    pdf, image, text = None, None, None
    if content.startswith(b"%PDF"):
        pdf = open_pdf(content)
    else:
        image = open_image(content)
        if image is None:
            text = decode_text(content)

    budgeted = Budgeted(pages=[], rest=[])
    page_count: int | None = None
    match spec:
        case TextExtract() if pdf is not None:
            page_count = len(pdf)
            budgeted = take_text(
                select_pages(spec.pages, page_count),
                lambda n: pdf_text(pdf, n),
                spec.max_chars,
            )
        case TextExtract() if text is not None:
            chunks = [
                text[i : i + spec.max_chars]
                for i in range(0, len(text), spec.max_chars)
            ]
            page_count = len(chunks)
            budgeted = take_text(
                select_pages(spec.pages, page_count),
                lambda n: chunks[n - 1],
                spec.max_chars,
            )
        case ImageExtract() if pdf is not None:
            page_count = len(pdf)
            budgeted = take_images(
                select_pages(spec.pages, page_count),
                lambda n: pdf_frame(pdf, n, spec),
                spec,
            )
        case ImageExtract() if image is not None:
            page_count = getattr(image, "n_frames", 1)
            budgeted = take_images(
                select_pages(spec.pages, page_count),
                lambda n: image_frame(image, n),
                spec,
            )
    return document(file, spec, page_count, budgeted)


def document(
    file: BytesResult, spec: Extract, page_count: int | None, budgeted: Budgeted
) -> DocumentResult:
    return DocumentResult(
        filename=file.name,
        content_type=file.media_type,
        size=len(file.content),
        sha256=hashlib.sha256(file.content).hexdigest(),
        mode=spec.mode,
        page_count=page_count,
        truncated=bool(budgeted.rest) or budgeted.clipped,
        next_pages=format_pages(budgeted.rest) or None,
        pages=budgeted.pages,
    )


def require_documents_extra() -> None:
    try:
        import PIL  # noqa: F401
        import pillow_heif  # noqa: F401
        import pypdfium2  # noqa: F401
    except ImportError as exc:
        raise ValueError(MISSING_DOCUMENTS_EXTRA) from exc


# --- page selection ---


def select_pages(spec: str | None, page_count: int) -> list[int]:
    if spec is None:
        return list(range(1, page_count + 1))
    pages: set[int] = set()
    for start, end in page_ranges(spec):
        if end > page_count:
            raise ValueError(
                f"pages {spec!r} asks past the last page; the file has {page_count}"
            )
        pages.update(range(start, end + 1))
    return sorted(pages)


def format_pages(pages: list[int]) -> str:
    """The inverse of ``page_ranges``: ``[1, 2, 3, 7]`` is ``"1-3,7"``."""
    runs: list[list[int]] = []
    for page in pages:
        if runs and page == runs[-1][-1] + 1:
            runs[-1].append(page)
        else:
            runs.append([page])
    return ",".join(
        str(run[0]) if len(run) == 1 else f"{run[0]}-{run[-1]}" for run in runs
    )


# --- budgets ---


def take_text(
    selected: list[int], page_text: Callable[[int], str], max_chars: int
) -> Budgeted:
    """``max_chars`` is a hard ceiling: a first page longer than it is clipped,
    and a later page that does not fit is left for ``next_pages``."""
    pages: list[TextPage | ImagePage] = []
    used = 0
    for i, page in enumerate(selected):
        text = page_text(page)
        room = max_chars - used
        if len(text) <= room:
            pages.append(TextPage(page=page, text=text))
            used += len(text)
        elif pages:
            return Budgeted(pages, selected[i:])
        else:
            return Budgeted(
                [TextPage(page=page, text=text[:room])], selected[i + 1 :], clipped=True
            )
    return Budgeted(pages, [])


def take_images(
    selected: list[int], frame: Callable[[int], Frame], spec: ImageExtract
) -> Budgeted:
    shown = selected[: spec.max_images]
    pages: list[TextPage | ImagePage] = [
        shrink(page, frame(page), spec) for page in shown
    ]
    return Budgeted(pages, selected[spec.max_images :])


# --- PDF ---


def open_pdf(content: bytes) -> "pypdfium2.PdfDocument":
    import pypdfium2

    try:
        return pypdfium2.PdfDocument(content)
    except pypdfium2.PdfiumError as exc:
        raise ValueError(f"not a readable PDF: {exc}") from exc


def pdf_text(pdf: "pypdfium2.PdfDocument", page: int) -> str:
    text: str = pdf[page - 1].get_textpage().get_text_bounded()
    return text


def pdf_frame(pdf: "pypdfium2.PdfDocument", page: int, spec: ImageExtract) -> Frame:
    """Rendered with the long side at ``max_long_side``, since PDF points are
    too coarse to read at 1:1; the original size is in points."""
    pdf_page = pdf[page - 1]
    width, height = pdf_page.get_size()
    image: Image = pdf_page.render(
        scale=spec.max_long_side / max(width, height)
    ).to_pil()
    return image, (round(width), round(height))


# --- images ---


def open_image(content: bytes) -> "Image | None":
    """``None`` when Pillow does not recognise the bytes as an image at all."""
    import pillow_heif
    from PIL import Image as PILImage
    from PIL import UnidentifiedImageError

    pillow_heif.register_heif_opener()
    try:
        return PILImage.open(io.BytesIO(content))
    except UnidentifiedImageError:
        return None
    except PILImage.DecompressionBombError as exc:
        raise ValueError(f"image too large to open: {exc}") from exc


def image_frame(image: "Image", page: int) -> Frame:
    """One frame, turned upright by its EXIF orientation."""
    from PIL import ImageOps

    try:
        image.seek(page - 1)
        upright = ImageOps.exif_transpose(image)
    except OSError as exc:
        raise ValueError(f"not a readable image: {exc}") from exc
    return upright, upright.size


def shrink(page: int, frame: Frame, spec: ImageExtract) -> ImagePage:
    """Re-encoded from pixels alone, so no EXIF (GPS included) survives."""
    image, (original_width, original_height) = frame
    rgb = image.convert("RGB")
    rgb.thumbnail((spec.max_long_side, spec.max_long_side))
    buffer = io.BytesIO()
    rgb.save(buffer, format="JPEG", quality=spec.quality)
    return ImagePage(
        page=page,
        image=buffer.getvalue(),
        width=rgb.width,
        height=rgb.height,
        original_width=original_width,
        original_height=original_height,
    )


# --- plain text ---


def decode_text(content: bytes) -> str | None:
    """Text, CSV, JSON and the like; ``None`` for any other binary."""
    if b"\x00" in content:
        return None
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None
