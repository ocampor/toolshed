"""Selector abstraction: Pydantic models for CSS, XPath, ID, and fallback selectors."""

from typing import Any

from pydantic import BaseModel

from llm_browser.drivers.base import Driver


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


def _selector_string(selector: Selector) -> str:
    match selector:
        case str():
            return selector
        case CssSelector(css=css):
            return css
        case XpathSelector(xpath=xpath):
            return f"xpath={xpath}"
        case IdSelector(id=el_id):
            return f'[id="{el_id}"]'
        case FallbackSelector():
            raise ValueError("FallbackSelector must be resolved via resolve_selector")
    raise ValueError(f"Unknown selector: {selector!r}")


def resolve_selector(driver: Driver, page: Any, selector: Selector) -> Any:
    """Resolve a typed selector into a driver-native locator."""
    if isinstance(selector, FallbackSelector):
        return _resolve_with_fallback(driver, page, selector.primary, selector.fallback)
    return driver.resolve(page, _selector_string(selector))


def expect_single(driver: Driver, locator: Any, selector: Selector) -> Any:
    """Validate that a locator matches exactly one element, return it."""
    count = driver.count(locator)
    if count > 1:
        raise ValueError(f"Expected 1 element for {selector!r}, found {count}")
    return driver.first(locator)


def _resolve_with_fallback(
    driver: Driver,
    page: Any,
    primary: SelectorSpec,
    fallback: SelectorSpec,
) -> Any:
    result = resolve_selector(driver, page, primary)
    if driver.count(result) > 0:
        return result
    return resolve_selector(driver, page, fallback)
