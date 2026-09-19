"""Selector abstraction: Pydantic models for CSS, XPath, ID, and fallback
selectors, plus the match-count rule a step's ``expect``/``pick`` states."""

from collections.abc import Callable
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel

from llm_browser.constants import MATCH_SAMPLES
from llm_browser.drivers.base import Driver
from llm_browser.results import AcceptedMatch, PickSpec


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


type SelectorSpec = (
    CssSelector | XpathSelector | IdSelector | FallbackSelector | RefSelector
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
    return driver.resolve(page, _selector_string(selector))


class MatchRule(NamedTuple):
    """How many elements a step's selector should match (``expect``), and which
    of them it acts on when there are more (``pick``)."""

    expect: int | Literal["many"] = 1
    pick: PickSpec | None = None


SINGLE = MatchRule(expect=1)
MANY = MatchRule(expect="many")


class Match(NamedTuple):
    """``locator`` is narrowed to the pick when there was one; ``nth`` says
    which match that was, and ``accepted`` the mismatch the pick took."""

    locator: Any
    nth: int | None = None
    accepted: AcceptedMatch | None = None


class MatchCountError(ValueError):
    """A selector matched a number of elements the step's ``expect`` rules out."""

    def __init__(
        self,
        expected: int | Literal["many"],
        found: int,
        samples: list[str],
        selector: Selector,
    ) -> None:
        self.expected = expected
        self.found = found
        self.samples = samples
        plural = "" if expected == 1 else "s"
        super().__init__(
            f"expected {expected} element{plural} for "
            f"'{describe_selector(selector)}', found {found}"
        )


PICK_INDEX: dict[str, Callable[[int], int]] = {
    "first": lambda found: 0,
    "last": lambda found: found - 1,
}


def pick_index(pick: PickSpec, found: int) -> int:
    """Which of ``found`` matches ``pick`` names."""
    if isinstance(pick, int):
        return pick
    return PICK_INDEX[pick](found)


def match_samples(driver: Driver, locator: Any, found: int) -> list[str]:
    return [
        (driver.text_content(driver.nth(locator, i)) or "").strip()
        for i in range(min(found, MATCH_SAMPLES))
    ]


def count_mismatch(rule: MatchRule, found: int, waiting: bool) -> bool:
    """Whether ``found`` breaks ``rule``.

    ``waiting`` is the check that runs before a wait, where too few matches is
    what the wait is for and only an ambiguity nothing picks from can fail.
    """
    if isinstance(rule.expect, int):
        if found > rule.expect and rule.pick is None:
            return True
        if found < rule.expect and not waiting:
            return True
    if waiting or rule.pick is None:
        return False
    return not 0 <= pick_index(rule.pick, found) < found


def narrowed(driver: Driver, locator: Any, rule: MatchRule, found: int) -> Match:
    if rule.pick is None:
        return Match(driver.first(locator) if rule.expect == 1 else locator)
    index = pick_index(rule.pick, found)
    mismatched = isinstance(rule.expect, int) and found != rule.expect
    return Match(
        driver.nth(locator, index),
        index,
        AcceptedMatch(expected=rule.expect, found=found, picked=rule.pick)
        if mismatched
        else None,
    )


def match_elements(
    driver: Driver,
    locator: Any,
    selector: Selector,
    rule: MatchRule = SINGLE,
    *,
    waiting: bool = False,
) -> Match:
    """Check what ``locator`` matches against ``rule``, narrowed to its pick.

    ``expect: many`` without a pick asks nothing of the count, so it never
    even counts.
    """
    if rule.expect == "many" and rule.pick is None:
        return Match(locator)
    found = driver.count(locator)
    if count_mismatch(rule, found, waiting):
        raise MatchCountError(
            rule.expect, found, match_samples(driver, locator, found), selector
        )
    if waiting:
        return Match(locator)
    return narrowed(driver, locator, rule, found)


def picked_element(driver: Driver, match: Match) -> Any:
    """The one element a many-match step acts on: its pick, or the first match."""
    return match.locator if match.nth is not None else driver.first(match.locator)


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
