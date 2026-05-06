"""HTML cleaning utilities for DOM snippet extraction and page snapshots."""

from lxml.html import (
    HtmlElement,
    HTMLParser,
    defs,
    document_fromstring,
    fragment_fromstring,
    tostring,
)
from lxml.html.clean import Cleaner

_page_parser = HTMLParser(remove_blank_text=True)

_cleaner = Cleaner(
    scripts=True,
    javascript=True,
    style=True,
    comments=True,
    inline_style=True,
    safe_attrs_only=False,
)

_page_cleaner = Cleaner(
    scripts=True,
    javascript=True,
    style=True,
    inline_style=True,
    comments=True,
    links=True,
    meta=True,
    page_structure=False,
    forms=False,
    frames=True,
    embedded=True,
    safe_attrs_only=True,
    safe_attrs=defs.safe_attrs - {"src", "href"},
    kill_tags=["svg"],
)


def _truncate_tree(element: HtmlElement, max_depth: int, current: int = 0) -> None:
    """Remove children beyond max_depth."""
    if current >= max_depth:
        for child in list(element):
            element.remove(child)
        return
    for child in element:
        _truncate_tree(child, max_depth, current + 1)


def sanitize_html_fragment(html: str, max_depth: int = 0) -> str:
    """Sanitize an HTML fragment; optionally truncate past max_depth nesting."""
    tree: HtmlElement = fragment_fromstring(html, create_parent=False)
    _cleaner(tree)
    if max_depth > 0:
        _truncate_tree(tree, max_depth)
    return _serialize(tree)


def sanitize_page_html(html: str) -> str:
    """Sanitize a full page for checkpoint capture."""
    tree: HtmlElement = document_fromstring(html, parser=_page_parser)
    _page_cleaner(tree)
    return _serialize(tree)


def _serialize(tree: HtmlElement) -> str:
    result: str = tostring(tree, encoding="unicode")
    return result
