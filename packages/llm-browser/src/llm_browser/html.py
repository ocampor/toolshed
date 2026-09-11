"""HTML cleaning utilities for DOM snippet extraction and page snapshots."""

import enum
import re
from typing import Any

from lxml import etree
from lxml.html import (
    HtmlElement,
    HTMLParser,
    defs,
    document_fromstring,
    fragment_fromstring,
    tostring,
)
from lxml.html.clean import Cleaner

from llm_browser.constants import (
    DATA_URI_PATTERN,
    EXTRA_SAFE_ATTRS,
    KILL_TAGS,
    STRUCTURAL_TAGS,
    URL_ATTRS,
    WHITESPACE_PRESERVE_TAGS,
    XHIGH_ATTRS,
)


class SanitizeLevel(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"


MEDIUM_ATTRS = defs.safe_attrs | EXTRA_SAFE_ATTRS - {"style"}
HIGH_ATTRS = MEDIUM_ATTRS - {"src", "href"}

# `None` keeps every attribute and every non-executable tag, svg included.
SAFE_ATTRS: dict[SanitizeLevel, frozenset[str] | None] = {
    SanitizeLevel.LOW: None,
    SanitizeLevel.MEDIUM: MEDIUM_ATTRS,
    SanitizeLevel.HIGH: HIGH_ATTRS,
    SanitizeLevel.XHIGH: XHIGH_ATTRS,
}

CLEANER_OPTIONS: dict[str, Any] = dict(
    scripts=True,
    javascript=True,
    style=True,
    comments=True,
    inline_style=True,
    links=True,
    meta=True,
    frames=False,
    embedded=False,
    forms=False,
    page_structure=False,
    remove_unknown_tags=False,
)

CLEANERS: dict[SanitizeLevel, Cleaner] = {
    level: Cleaner(
        safe_attrs_only=attrs is not None,
        safe_attrs=attrs or frozenset(),
        kill_tags=[] if attrs is None else list(KILL_TAGS),
        **CLEANER_OPTIONS,
    )
    for level, attrs in SAFE_ATTRS.items()
}

_page_parser = HTMLParser(remove_blank_text=True)

# A tail sits outside its element, so `pre` preserves its own text but not its
# tail: in XPath a tail is a child of the *enclosing* element, not of `pre`.
_PRESERVED = " or ".join(
    f"ancestor-or-self::{tag}" for tag in sorted(WHITESPACE_PRESERVE_TAGS)
)
COLLAPSIBLE_TEXT = f"//text()[not({_PRESERVED})]"


def truncate_data_uris(tree: HtmlElement) -> None:
    for node in tree.iter(tag=etree.Element):
        for attr in URL_ATTRS:
            value = node.get(attr)
            if value and value.startswith("data:"):
                node.set(attr, DATA_URI_PATTERN.sub(r"\1", value))


def normalize_whitespace(tree: HtmlElement) -> None:
    # `strip_tags` can leave two adjacent text nodes that XPath reports
    # separately, so read the merged value off the element rather than the node.
    for node in tree.xpath(COLLAPSIBLE_TEXT):
        owner: HtmlElement = node.getparent()
        value = owner.tail if node.is_tail else owner.text
        if not value:
            continue
        collapsed = re.sub(r"\s+", " ", value) if value.strip() else None
        if node.is_tail:
            owner.tail = collapsed
        else:
            owner.text = collapsed


def truncate_tree(element: HtmlElement, max_depth: int, current: int = 0) -> None:
    """Remove children beyond max_depth."""
    if current >= max_depth:
        for child in list(element):
            element.remove(child)
        return
    for child in element:
        truncate_tree(child, max_depth, current + 1)


def sanitize_tree(tree: HtmlElement, level: SanitizeLevel) -> None:
    """Apply ``level`` to ``tree``, in place.

    The one implementation of what a level *means*. Both entry points — a
    fragment from `dom`, a whole document from a failure capture — go through
    it, so a page snapshot at ``medium`` keeps exactly the attributes a
    snippet at ``medium`` keeps.
    """
    CLEANERS[level](tree)
    if level is not SanitizeLevel.LOW:
        truncate_data_uris(tree)
    if level is SanitizeLevel.XHIGH:
        # Never touches the root, so a structural root keeps its tag and attrs.
        etree.strip_tags(tree, *STRUCTURAL_TAGS)
    normalize_whitespace(tree)


def sanitize_html_fragment(
    html: str,
    max_depth: int = 0,
    level: SanitizeLevel = SanitizeLevel.LOW,
) -> str:
    """Sanitize an HTML fragment; optionally truncate past max_depth nesting."""
    tree: HtmlElement = fragment_fromstring(html, create_parent=False)
    sanitize_tree(tree, level)
    if max_depth > 0:
        truncate_tree(tree, max_depth)
    return serialize(tree)


def sanitize_page_html(html: str, level: SanitizeLevel = SanitizeLevel.HIGH) -> str:
    """Sanitize a whole page for a failure capture.

    ``high`` by default — a capture is for reading, and every `src`/`href` in
    a full page is noise — but the caller decides: ``medium`` keeps links when
    the point is to see where the page would have gone next, ``xhigh``
    collapses the wrappers when the point is to read the structure.
    """
    tree: HtmlElement = document_fromstring(html, parser=_page_parser)
    sanitize_tree(tree, level)
    return serialize(tree)


def serialize(tree: HtmlElement) -> str:
    result: str = tostring(tree, encoding="unicode")
    return result
