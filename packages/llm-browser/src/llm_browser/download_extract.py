"""What a ``download`` step's ``extract:`` asks for — distinct from a ``read``
step's ``extract:``, which maps DOM fields to rows."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from yaml_engine.template import template_names

from llm_browser.constants import (
    EXTRACT_JPEG_QUALITY,
    EXTRACT_LONG_SIDE_CEILING,
    EXTRACT_MAX_CHARS,
    EXTRACT_MAX_CHARS_CEILING,
    EXTRACT_MAX_IMAGES,
    EXTRACT_MAX_IMAGES_CEILING,
    EXTRACT_MAX_LONG_SIDE,
    EXTRACT_PAGE_OVERHEAD_CHARS,
    EXTRACT_PAGES_MAX_LENGTH,
)


def pages_named(spec: str, last_page: int) -> list[int]:
    """``"1-3,7"`` is ``[1, 2, 3, 7]``, without pages past ``last_page``."""
    # gotcha: recursion depth is bounded by EXTRACT_PAGES_MAX_LENGTH (at most 100 parts)
    head, comma, rest = spec.partition(",")
    first, last = bounds_of(head)
    pages = list(range(first, min(last, last_page) + 1))
    if comma:
        pages += pages_named(rest, last_page)
    return pages


def spec_of(pages: list[int]) -> str:
    """``[1, 2, 3, 7]`` is ``"1-3,7"``, the inverse of ``pages_named``; ``pages`` is not empty."""
    run, rest = leading_run(pages)
    head = str(run[0]) if len(run) == 1 else f"{run[0]}-{run[-1]}"
    if rest:
        head += "," + spec_of(rest)
    return head


def bounds_of(part: str) -> tuple[int, int]:
    first, dash, last = part.strip().partition("-")
    if not dash:
        last = first
    if not (first.isdecimal() and last.isdecimal()):
        raise ValueError(f"invalid page range {part!r}; use N or N-M, e.g. '1-3,7'")
    if int(first) < 1 or int(last) < int(first):
        raise ValueError(
            f"invalid page range {part!r}; pages start at 1, N-M needs N <= M"
        )
    return int(first), int(last)


def leading_run(pages: list[int]) -> tuple[list[int], list[int]]:
    end = 1
    while end < len(pages) and pages[end] == pages[end - 1] + 1:
        end += 1
    return pages[:end], pages[end:]


class PageSelection(BaseModel, extra="forbid"):
    pages: str | None = Field(
        None,
        max_length=EXTRACT_PAGES_MAX_LENGTH,
        description="1-based pages, e.g. `1-3,7`; unset means all.",
    )

    @field_validator("pages")
    @classmethod
    def _check_pages(cls, pages: str | None) -> str | None:
        # A templated value is checked again once ``resolve_step_templates`` fills it.
        if pages is not None and not template_names(pages):
            pages_named(pages, last_page=0)
        return pages


class TextExtract(PageSelection):
    """Each page's text layer (``""`` for a page with none). Text files (CSV,
    JSON, plain text) are cut into fixed-size chunks, never ``clipped``, so
    ``next_pages`` only lines up when the next call uses the same ``max_chars``."""

    mode: Literal["text"]
    max_chars: int = Field(
        EXTRACT_MAX_CHARS,
        ge=EXTRACT_PAGE_OVERHEAD_CHARS + 1,
        le=EXTRACT_MAX_CHARS_CEILING,
        description="Characters of page text returned per step, each page's fixed overhead included.",
    )


class ImageExtract(PageSelection):
    """Each page rendered as a JPEG, shrunk server-side, with no metadata."""

    mode: Literal["images"]
    max_images: int = Field(
        EXTRACT_MAX_IMAGES,
        ge=1,
        le=EXTRACT_MAX_IMAGES_CEILING,
        description="Images returned per step, at most.",
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
