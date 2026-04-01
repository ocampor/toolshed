"""HTML cleaning utilities for DOM snippet extraction."""

from lxml.html import fragment_fromstring, tostring
from lxml.html.clean import Cleaner

_cleaner = Cleaner(
    scripts=True,
    javascript=True,
    style=True,
    comments=True,
    inline_style=True,
    safe_attrs_only=True,
)


def _truncate_tree(element: object, max_depth: int, current: int = 0) -> None:
    """Remove children beyond max_depth."""
    if current >= max_depth:
        for child in list(element):  # type: ignore[call-overload]
            element.remove(child)  # type: ignore[union-attr]
        return
    for child in element:  # type: ignore[call-overload]
        _truncate_tree(child, max_depth, current + 1)


def clean_html(html: str, max_depth: int = 0) -> str:
    """Clean HTML by stripping scripts, styles, comments, and inline styles.

    max_depth limits nesting depth (0 = no limit).
    """
    cleaned = _cleaner.clean_html(html)
    if max_depth <= 0:
        return cleaned
    tree = fragment_fromstring(cleaned, create_parent=False)
    _truncate_tree(tree, max_depth)
    return tostring(tree, encoding="unicode")
