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


def select_pages(spec: str | None, page_count: int) -> list[int]:
    """The pages ``spec`` names that the file has; naming none of them raises."""
    if spec is None:
        return list(range(1, page_count + 1))
    named: set[int] = set()
    for start, end in page_ranges(spec):
        # Clamped before expanding: "1-100000000" must not build 1e8 ints.
        last = min(end, page_count)
        named.update(range(start, last + 1))
    pages = sorted(named)
    if not pages:
        raise ValueError(f"pages {spec!r} are all past the last page ({page_count})")
    return pages


def format_pages(pages: list[int]) -> str:
    """The inverse of ``page_ranges``: ``[1, 2, 3, 7]`` is ``"1-3,7"``."""
    runs: list[list[int]] = []
    for page in pages:
        if runs and page == runs[-1][-1] + 1:
            runs[-1].append(page)
        else:
            runs.append([page])
    parts = []
    for run in runs:
        first, last = run[0], run[-1]
        parts.append(str(first) if first == last else f"{first}-{last}")
    return ",".join(parts)


class PageSelection(BaseModel, extra="forbid"):
    pages: str | None = Field(
        None, description="1-based pages, e.g. `1-3,7`; unset means all."
    )

    @field_validator("pages")
    @classmethod
    def _check_pages(cls, pages: str | None) -> str | None:
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
    """Each page rendered as a JPEG, shrunk server-side, with no metadata."""

    mode: Literal["images"]
    max_images: int = Field(
        EXTRACT_MAX_IMAGES, ge=1, description="Images returned per step, at most."
    )
    max_long_side: int = Field(
        EXTRACT_MAX_LONG_SIDE,
        ge=1,
        le=EXTRACT_LONG_SIDE_CEILING,
        description="Pixels; images shrink to it, PDF pages render at it.",
    )
    quality: int = Field(
        EXTRACT_JPEG_QUALITY,
        ge=1,
        le=95,
        description="JPEG quality of each image.",
    )


Extract = Annotated[TextExtract | ImageExtract, Field(discriminator="mode")]
