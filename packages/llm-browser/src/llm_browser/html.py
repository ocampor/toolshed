"""HTML cleaning utilities for DOM snippet extraction and page snapshots."""

import enum
import re
from collections.abc import Callable, Iterator
from typing import Any

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


_page_parser = HTMLParser(remove_blank_text=True)

_low_cleaner = Cleaner(
    scripts=True,
    javascript=True,
    style=True,
    comments=True,
    inline_style=True,
    safe_attrs_only=False,
    remove_unknown_tags=False,
)

# The three restricted levels differ only in which attributes survive; every
# other cleaning decision is shared.
RESTRICTED_OPTIONS: dict[str, Any] = dict(
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
    safe_attrs_only=True,
    kill_tags=list(KILL_TAGS),
    remove_unknown_tags=False,
)

MEDIUM_ATTRS = defs.safe_attrs | EXTRA_SAFE_ATTRS - {"style"}
HIGH_ATTRS = MEDIUM_ATTRS - {"src", "href"}

CLEANERS: dict[SanitizeLevel, Cleaner] = {
    SanitizeLevel.LOW: _low_cleaner,
    SanitizeLevel.MEDIUM: Cleaner(safe_attrs=MEDIUM_ATTRS, **RESTRICTED_OPTIONS),
    SanitizeLevel.HIGH: Cleaner(safe_attrs=HIGH_ATTRS, **RESTRICTED_OPTIONS),
    SanitizeLevel.XHIGH: Cleaner(safe_attrs=XHIGH_ATTRS, **RESTRICTED_OPTIONS),
}

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


def iter_elements(tree: HtmlElement) -> Iterator[HtmlElement]:
    return (node for node in tree.iter() if isinstance(node.tag, str))


def truncate_data_uris(tree: HtmlElement) -> None:
    for node in iter_elements(tree):
        for attr in URL_ATTRS:
            value = node.get(attr)
            if value and value.startswith("data:"):
                node.set(attr, DATA_URI_PATTERN.sub(r"\1", value))


def is_blank_wrapper(node: HtmlElement, root: HtmlElement) -> bool:
    if node is root or node.tag not in STRUCTURAL_TAGS:
        return False
    return not (node.text and node.text.strip())


def drop_empty_structural(tree: HtmlElement) -> bool:
    dropped = False
    for node in list(iter_elements(tree)):
        if not is_blank_wrapper(node, tree) or len(node):
            continue
        parent = node.getparent()
        if node.tail:
            previous = node.getprevious()
            if previous is not None:
                previous.tail = (previous.tail or "") + node.tail
            else:
                parent.text = (parent.text or "") + node.tail
        parent.remove(node)
        dropped = True
    return dropped


def unwrap_structural(tree: HtmlElement) -> bool:
    unwrapped = False
    for node in list(iter_elements(tree)):
        if not is_blank_wrapper(node, tree) or node.attrib or len(node) != 1:
            continue
        child = node[0]
        child.tail = (child.tail or "") + (node.tail or "")
        node.getparent().replace(node, child)
        unwrapped = True
    return unwrapped


def collapse_structural(tree: HtmlElement) -> None:
    while True:
        dropped = drop_empty_structural(tree)
        unwrapped = unwrap_structural(tree)
        if not (dropped or unwrapped):
            return


def inside_preserved(node: HtmlElement) -> bool:
    return any(a.tag in WHITESPACE_PRESERVE_TAGS for a in node.iterancestors())


def collapse_text(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return re.sub(r"\s+", " ", value)


def normalize_whitespace(tree: HtmlElement) -> None:
    # A node's tail sits outside it, so `pre` preserves its own text but not its tail.
    for node in iter_elements(tree):
        if inside_preserved(node):
            continue
        if node.tag not in WHITESPACE_PRESERVE_TAGS:
            node.text = collapse_text(node.text)
        node.tail = collapse_text(node.tail)


LEVEL_PASSES: dict[SanitizeLevel, tuple[Callable[[HtmlElement], None], ...]] = {
    SanitizeLevel.LOW: (),
    SanitizeLevel.MEDIUM: (truncate_data_uris,),
    SanitizeLevel.HIGH: (truncate_data_uris,),
    SanitizeLevel.XHIGH: (truncate_data_uris, collapse_structural),
}


def _truncate_tree(element: HtmlElement, max_depth: int, current: int = 0) -> None:
    """Remove children beyond max_depth."""
    if current >= max_depth:
        for child in list(element):
            element.remove(child)
        return
    for child in element:
        _truncate_tree(child, max_depth, current + 1)


def sanitize_html_fragment(
    html: str,
    max_depth: int = 0,
    level: SanitizeLevel = SanitizeLevel.LOW,
) -> str:
    """Sanitize an HTML fragment; optionally truncate past max_depth nesting."""
    tree: HtmlElement = fragment_fromstring(html, create_parent=False)
    CLEANERS[level](tree)
    for level_pass in LEVEL_PASSES[level]:
        level_pass(tree)
    normalize_whitespace(tree)
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
