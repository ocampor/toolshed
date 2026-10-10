"""What a ``download`` step's ``extract:`` asks for — distinct from a ``read``
step's ``extract:``, which maps DOM fields to rows."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from llm_browser.constants import (
    EXTRACT_JPEG_QUALITY,
    EXTRACT_LONG_SIDE_CEILING,
    EXTRACT_MAX_CHARS,
    EXTRACT_MAX_IMAGES,
    EXTRACT_MAX_LONG_SIDE,
)


def page_ranges(spec: str) -> list[tuple[int, int]]:
    """``"1-3,7"`` as 1-based inclusive ranges; any malformed part raises."""
    ranges = []
    for part in spec.split(","):
        first, _, last = part.strip().partition("-")
        if not first.isdigit() or not (last or first).isdigit():
            raise ValueError(f"invalid page range {part!r}; use N or N-M, e.g. '1-3,7'")
        start, end = int(first), int(last or first)
        if start < 1 or end < start:
            raise ValueError(
                f"invalid page range {part!r}; pages start at 1, N-M needs N <= M"
            )
        ranges.append((start, end))
    return ranges


class PageSelection(BaseModel, extra="forbid"):
    pages: str | None = Field(
        None, description="1-based pages, e.g. `1-3,7`; unset means all."
    )

    @field_validator("pages")
    @classmethod
    def check_pages(cls, pages: str | None) -> str | None:
        if pages is not None:
            page_ranges(pages)
        return pages


class TextExtract(PageSelection):
    """Each page's text layer (``""`` for a page with none); text files are cut
    into pages of ``max_chars``."""

    mode: Literal["text"]
    max_chars: int = Field(
        EXTRACT_MAX_CHARS, ge=1, description="Hard ceiling on text returned per step."
    )


class ImageExtract(PageSelection):
    """Each page rendered as a JPEG, shrunk server-side, EXIF stripped."""

    mode: Literal["images"]
    max_images: int = Field(EXTRACT_MAX_IMAGES, ge=1)
    max_long_side: int = Field(
        EXTRACT_MAX_LONG_SIDE, ge=1, le=EXTRACT_LONG_SIDE_CEILING
    )
    quality: int = Field(EXTRACT_JPEG_QUALITY, ge=1, le=95)


Extract = Annotated[TextExtract | ImageExtract, Field(discriminator="mode")]
