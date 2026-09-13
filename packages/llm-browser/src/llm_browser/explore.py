"""``explore`` and the rules it answers with: verdict, candidates, stability."""

import re
import time
from collections.abc import Callable, Collection
from typing import TYPE_CHECKING, Any

from llm_browser import constants
from llm_browser.explore_models import (
    ExploreRead,
    ExploreResult,
    FirstMatch,
    Intent,
    Locators,
    Stability,
    Verdict,
)
from llm_browser.parse import ExtractField, parse_extract_spec, row_spec
from llm_browser.scripts import explore_first_js
from llm_browser.selectors import Selector, describe_selector

if TYPE_CHECKING:
    from llm_browser.session import BrowserSession

# Every intent but ``read`` wants exactly one match; these say what else it
# wants of that match.
READY: dict[Intent, Callable[[FirstMatch], bool]] = {
    Intent.READ: lambda first: True,
    Intent.WAIT: lambda first: True,
    Intent.CLICK: lambda first: first.clickable,
    Intent.FILL: lambda first: first.visible and first.enabled,
}


def verdict_for(intent: Intent, count: int, first: FirstMatch | None) -> Verdict:
    """Whether a step with this ``intent`` can be written against the selector.

    A ``read`` is happy with any number of matches — that is what it is for —
    so only the other three call two matches ambiguous.
    """
    if count == 0 or first is None:
        return Verdict.MISSING
    if intent is Intent.READ:
        return Verdict.OK
    if count > 1:
        return Verdict.AMBIGUOUS
    return Verdict.OK if READY[intent](first) else Verdict.NOT_ACTIONABLE


def accepted_counts(intent: Intent, count: int) -> set[int]:
    """What a candidate has to match to be one.

    Every intent but ``read`` is after one element. A ``read`` is after the
    list: a candidate that finds one of thirty rows is not a selector to write
    in its place, whatever else it is.
    """
    return {count} if intent is Intent.READ else {1}


CLASS_TOKENS = re.compile(r"\.([A-Za-z0-9_-]+)")
POSITIONAL_PARTS = re.compile(r":nth-|:first-child|:last-child|\[\d+\]")


def hashed_class(token: str) -> bool:
    """Whether a class name reads as a build artefact rather than a name.

    ``css-1x2y3z`` and ``_2hJk`` have a segment mixing letters and digits;
    ``grid-cols-12`` and ``text-lg`` do not.
    """
    return any(
        len(part) >= 4
        and any(c.isdigit() for c in part)
        and any(c.isalpha() for c in part)
        for part in re.split(r"[-_]", token)
    )


def selector_stability(selector: str) -> Stability:
    """How much of ``selector`` the next redeploy is likely to take with it."""
    if "data-testid" in selector or "data-testing-id" in selector:
        return Stability.DATA_TESTID
    if "aria-label" in selector or selector.startswith("role="):
        return Stability.ARIA
    if "#" in selector or "[id=" in selector:
        return Stability.ID
    if any(hashed_class(token) for token in CLASS_TOKENS.findall(selector)):
        return Stability.CLASS_HASH
    if POSITIONAL_PARTS.search(selector):
        return Stability.POSITIONAL
    return Stability.OTHER


# --- Candidates: what to write instead of the selector that was explored ---

CSS_UNSAFE = re.compile(r"([^A-Za-z0-9_-])")
CSS_STRING_UNSAFE = re.compile(r'["\\]|[\x00-\x1f\x7f]')


def css_quoted(value: str) -> str:
    """``value`` as a CSS string.

    What ``CSS.escape`` does for an identifier, for the quoted half: a value
    carrying a quote, a backslash or a newline would otherwise end the string
    early and make the candidate a selector for something else.
    """
    escaped = CSS_STRING_UNSAFE.sub(
        lambda m: (
            f"\\{ord(m.group()):x} "
            if m.group() < " " or m.group() == "\x7f"
            else "\\" + m.group()
        ),
        value,
    )
    return f'"{escaped}"'


def escaped_id(value: str) -> str:
    """``value`` as a CSS identifier, the way ``CSS.escape`` writes one."""
    return CSS_UNSAFE.sub(r"\\\1", value)


def generated_id(value: str) -> bool:
    """An id a redeploy will renumber: `react-select-2-input`, a uuid, a hash."""
    return any(c.isdigit() for c in value) or len(value) > 40


def href_prefix(href: str) -> str | None:
    """The part of a link's path that names the section rather than the page.

    ``/item?id=123`` is every item, ``/jobs/data-eng-4821`` is every job. A
    trailing segment that carries a number is the page; what is left is the
    section, and ``None`` when nothing is.
    """
    path = href.split("?")[0].split("#")[0]
    segments = path.split("/")
    kept = list(segments)
    while kept and (not kept[-1] or generated_id(kept[-1])):
        kept.pop()
    if not any(kept):
        return None
    prefix = "/".join(kept) if kept == segments else f"{'/'.join(kept)}/"
    # Nothing was generalized: `a[href^=<the whole href>]` is the link itself
    # spelled longer.
    return prefix if prefix != href else None


def scoped_testid(locators: Locators) -> str:
    """The test id as a selector for the match, not for whatever carries it.

    A test id on an ancestor names the row; the match is the element inside
    it, so the candidate has to descend — ``:is()`` keeps that tail from
    adding specificity it has not earned.
    """
    attribute = f"[{locators.testid_attribute}={css_quoted(locators.testid or '')}]"
    if not locators.testid_depth:
        return attribute
    return f"{attribute} :is({locators.tag})"


def candidate_selectors(locators: Locators, *, role_selectors: bool) -> list[str]:
    """Sturdier selectors for the first match, best first — one per kind.

    A test id survives a redesign; an aria label survives a restyle; an id
    survives both unless it was generated; a link's section outlives the page
    it points at; a hashed class outlives nothing but the markup around it.
    One proposal per kind, so an element carrying eight hashed classes still
    offers the caller three verifiable candidates rather than three classes.
    Nothing here is checked to match — that is the caller's count.

    ``role_selectors`` is the driver's: ``role=…`` is Playwright's own syntax,
    and a candidate an author cannot run under their driver is not one.
    """
    proposals: list[str] = []
    if locators.testid and locators.testid_attribute:
        proposals.append(scoped_testid(locators))
    if locators.aria_label:
        proposals.append(f"[aria-label={css_quoted(locators.aria_label)}]")
    if role_selectors and locators.role and locators.name:
        proposals.append(f"role={locators.role}[name={css_quoted(locators.name)}]")
    if locators.id and not generated_id(locators.id):
        proposals.append(f"#{escaped_id(locators.id)}")
    prefix = href_prefix(locators.href) if locators.href else None
    if prefix:
        proposals.append(f"a[href^={css_quoted(prefix)}]")
    hashed = [token for token in locators.classes if hashed_class(token)]
    # Escaped: a Tailwind bracket class (`w-[42px]`) reads as hashed and is
    # not a selector until its brackets are.
    proposals += [f".{escaped_id(token)}" for token in hashed[:1]]
    return proposals


def cut(value: str | None, limit: int) -> str | None:
    """A sampled field, shortened. `None` and `""` stay themselves."""
    return value[:limit] if value else value


def empty_everywhere(
    rows: list[dict[str, str | None]], fields: Collection[str]
) -> list[str]:
    """Fields that no sampled row filled in — missing and blank both count."""
    if not rows:
        return []
    return [name for name in fields if not any(row[name] for row in rows)]


def explore(
    session: "BrowserSession",
    selector: Selector,
    extract: dict[str, ExtractField] | None = None,
    sample: int = constants.EXPLORE_SAMPLE_ROWS,
    timeout_ms: int = constants.DEFAULT_WAIT_TIMEOUT_MS,
    intent: Intent = Intent.READ,
    sample_chars: int = constants.EXPLORE_SAMPLE_CHARS,
) -> ExploreResult:
    """Count and sample what ``selector`` matches.

    Never clicks; scrolls an offscreen match into view so the hit test has
    an answer, which is what the click path does before it clicks.

    For writing a step against a page you have not read yet: how many
    elements the selector really finds, what the first ``sample`` of them
    say under ``extract`` (the row's own text when it is omitted), which
    fields stayed empty, and — in ``first`` — whether a click or a fill
    would actually land. ``verdict`` reads all of that against ``intent``.
    A selector that never arrives is a count of zero, not a
    ``TimeoutError`` — "nothing here" is the answer. Each sampled field is
    cut to ``sample_chars``: reading a row whole is what ``read`` is for.
    """
    stability = selector_stability(describe_selector(selector))
    started = time.monotonic()
    try:
        locator = session.find_all(selector, timeout=timeout_ms)
    except TimeoutError:
        return ExploreResult(
            count=0, sample=[], empty_fields=[], text_chars=0, stability=stability
        )
    since_call_ms = round((time.monotonic() - started) * 1000)
    count = session.driver.count(locator)
    spec = row_spec(extract or parse_extract_spec(None))
    # Only the sampled elements are read: `sample x (fields + 1)`
    # per-element reads (the +1 is `text_chars`), whatever `count` is.
    elements = [session.driver.nth(locator, i) for i in range(min(sample, count))]
    rows = [
        {
            name: cut(session.driver.read_field(element, field), sample_chars)
            for name, field in spec.items()
        }
        for element in elements
    ]
    found = session.first_match(locator) if count else None
    first = found.first if found else None
    return ExploreResult(
        count=count,
        sample=rows,
        empty_fields=empty_everywhere(rows, spec),
        text_chars=sum(
            len(session.driver.read_property(el, "innerText") or "") for el in elements
        ),
        first=first,
        since_navigation_ms=found.since_navigation_ms if found else None,
        since_call_ms=since_call_ms,
        candidates=session.verified_candidates(
            candidate_selectors(
                found.locators,
                role_selectors=session.driver.supports_role_selector,
            )
            if found
            else [],
            accepted_counts(intent, count),
        ),
        stability=stability,
        verdict=verdict_for(intent, count, first),
    )


def first_match(session: "BrowserSession", locator: Any) -> ExploreRead:
    """The first match as a click would find it, what it offers a selector,
    and how long the page had been up — one page evaluation for all three."""
    raw = session.driver.evaluate(session.driver.first(locator), explore_first_js())
    return ExploreRead.model_validate(raw)


def verified_candidates(
    session: "BrowserSession", proposals: list[str], accepted: Collection[int]
) -> list[str]:
    """The proposals whose own count is one ``accepted`` here.

    Only the best ``EXPLORE_MAX_CANDIDATES`` proposals are checked — one
    count each, so ``explore`` costs a bounded number of round trips
    however many things the element could be called.

    A unique match *is* the first match: every proposal was built from
    something read off it (or off the row carrying it).
    """
    checked = proposals[: constants.EXPLORE_MAX_CANDIDATES]
    return [
        candidate for candidate in checked if session.count_of(candidate) in accepted
    ]
