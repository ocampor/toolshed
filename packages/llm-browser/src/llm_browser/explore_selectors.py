"""Selector rules: how sturdy a selector is, and what to write instead.

The page reports what an element offers — a test id, a label, an id, a href, a
class — and these rules say which of those make a selector and in what order.
Shared by ``explore`` and ``survey``: one page, one vocabulary of selectors.
"""

import re

from llm_browser.explore_models import Locators, Stability


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
