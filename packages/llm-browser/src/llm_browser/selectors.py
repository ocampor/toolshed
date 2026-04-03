"""Selector abstraction: Pydantic models for CSS, XPath, ID, and fallback selectors."""

from typing import Any

from pydantic import BaseModel
from patchright.sync_api import Frame, Locator, Page

type PageLike = Page | Frame


class CssSelector(BaseModel):
    """Explicit CSS selector."""

    css: str


class XpathSelector(BaseModel):
    """Explicit XPath selector."""

    xpath: str


class IdSelector(BaseModel):
    """Shorthand for [id="..."] attribute selector."""

    id: str


class FallbackSelector(BaseModel):
    """Try primary selector first, fall back if no match found."""

    primary: "CssSelector | XpathSelector | IdSelector | FallbackSelector"
    fallback: "CssSelector | XpathSelector | IdSelector | FallbackSelector"


type SelectorSpec = CssSelector | XpathSelector | IdSelector | FallbackSelector
type Selector = str | SelectorSpec

FallbackSelector.model_rebuild()


def parse_selector(raw: str | dict[str, Any]) -> Selector:
    """Parse a raw string or dict into a typed Selector.

    Used at the boundary where YAML/JSON data enters the system.
    """
    if isinstance(raw, str):
        return raw
    if isinstance(raw, BaseModel):
        return raw
    if "css" in raw:
        return CssSelector.model_validate(raw)
    if "xpath" in raw:
        return XpathSelector.model_validate(raw)
    if "id" in raw:
        return IdSelector.model_validate(raw)
    if "primary" in raw:
        return FallbackSelector.model_validate(raw)
    raise ValueError(f"Unknown selector format: {raw!r}")


def resolve_selector(page: PageLike, selector: Selector) -> Locator:
    """Resolve a typed selector into a Playwright Locator."""
    match selector:
        case str():
            return page.locator(selector)
        case CssSelector(css=css):
            return page.locator(css)
        case XpathSelector(xpath=xpath):
            return page.locator(f"xpath={xpath}")
        case IdSelector(id=el_id):
            return page.locator(f'[id="{el_id}"]')
        case FallbackSelector(primary=primary, fallback=fallback):
            return _resolve_with_fallback(page, primary, fallback)
    raise ValueError(f"Unknown selector: {selector!r}")


def expect_single(locator: Locator, selector: Selector) -> Locator:
    """Validate that a locator matches exactly one element, return it."""
    count = locator.count()
    if count > 1:
        raise ValueError(f"Expected 1 element for {selector!r}, found {count}")
    return locator.first


def _resolve_with_fallback(
    page: PageLike, primary: SelectorSpec, fallback: SelectorSpec
) -> Locator:
    result = resolve_selector(page, primary)
    if result.count() > 0:
        return result
    return resolve_selector(page, fallback)
