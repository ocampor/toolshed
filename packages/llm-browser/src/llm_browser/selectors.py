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


class RefSelector(BaseModel):
    """A selector named symbolically; the run's selector map supplies it."""

    ref: str


class FallbackSelector(BaseModel):
    """Try primary selector first, fall back if no match found."""

    primary: "CssSelector | XpathSelector | IdSelector | FallbackSelector"
    fallback: "CssSelector | XpathSelector | IdSelector | FallbackSelector"


PlainSelector = str | CssSelector | XpathSelector | IdSelector | FallbackSelector


class ScopedSelector(BaseModel):
    """``inner``, looked for inside the ``index``-th match of ``root``.

    What a step's ``in: <as>`` builds, once per pass: the root is re-resolved
    and re-indexed every time, so no handle outlives the pass that made it.
    """

    root: PlainSelector
    index: int
    inner: PlainSelector


type SelectorSpec = (
    CssSelector
    | XpathSelector
    | IdSelector
    | FallbackSelector
    | RefSelector
    | ScopedSelector
)
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
    if "ref" in raw:
        return RefSelector.model_validate(raw)
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
        case ScopedSelector():
            raise ValueError("ScopedSelector must be resolved via resolve_selector")
        case RefSelector(ref=ref):
            raise ValueError(f"selector ref {ref!r} was never resolved from a map")
    raise ValueError(f"Unknown selector: {selector!r}")


def describe_selector(selector: Selector) -> str:
    """The selector as a user would have written it, for error messages.

    Total, unlike ``css_string`` and ``_selector_string``: an XPath renders as
    ``xpath=...`` and a fallback chain as ``primary or fallback``, so no
    caller has to fall back to a pydantic repr.
    """
    if isinstance(selector, FallbackSelector):
        primary = describe_selector(selector.primary)
        return f"{primary} or {describe_selector(selector.fallback)}"
    if isinstance(selector, ScopedSelector):
        root = describe_selector(selector.root)
        return f"{root}[{selector.index}] {describe_selector(selector.inner)}"
    return _selector_string(selector)


def css_string(selector: Selector) -> str:
    """CSS text for an in-page ``querySelector`` call.

    XPath and fallback selectors have no CSS form; they need a driver locator.
    """
    match selector:
        case str() | CssSelector() | IdSelector():
            return _selector_string(selector)
    raise ValueError(f"{selector!r} has no CSS form; a CSS or id selector is required")


def resolve_selector(driver: Driver, page: Any, selector: Selector) -> Any:
    """Resolve a typed selector into a driver-native locator."""
    if isinstance(selector, FallbackSelector):
        return _resolve_with_fallback(driver, page, selector.primary, selector.fallback)
    if isinstance(selector, ScopedSelector):
        return _resolve_scoped(driver, page, selector)
    return driver.resolve(page, _selector_string(selector))


def _resolve_scoped(driver: Driver, page: Any, selector: ScopedSelector) -> Any:
    """Descendants of one match only. The count is checked first: a page that
    dropped rows mid-loop fails the pass with what happened, not with whatever
    a driver does when asked for an element that is no longer there."""
    if isinstance(selector.inner, FallbackSelector):
        raise ValueError(
            "a fallback selector cannot be scoped to an element with `in:`; "
            "name one selector"
        )
    root = resolve_selector(driver, page, selector.root)
    count = driver.count(root)
    if count <= selector.index:
        raise ValueError(
            f"{describe_selector(selector.root)} matches {count} elements now, "
            f"so element {selector.index} is gone"
        )
    element = driver.nth(root, selector.index)
    return driver.child(element, _selector_string(selector.inner))


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
    # Resolution asks "does the primary match right now"; every caller waits
    # for the state it wants afterwards.
    if driver.count(result) > 0:
        return result
    return resolve_selector(driver, page, fallback)
