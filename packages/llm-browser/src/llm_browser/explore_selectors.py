import re

from llm_browser.explore_models import Locators, Stability


CLASS_TOKENS = re.compile(r"\.([A-Za-z0-9_-]+)")
POSITIONAL_PARTS = re.compile(r":nth-|:first-child|:last-child|\[\d+\]")


def hashed_class(token: str) -> bool:
    """``css-1x2y3z`` and ``_2hJk`` mix letters and digits in a segment; ``grid-cols-12`` does not."""
    return any(
        len(part) >= 4
        and any(c.isdigit() for c in part)
        and any(c.isalpha() for c in part)
        for part in re.split(r"[-_]", token)
    )


def selector_stability(selector: str) -> Stability:
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


CSS_UNSAFE = re.compile(r"([^A-Za-z0-9_-])")
CSS_STRING_UNSAFE = re.compile(r'["\\]|[\x00-\x1f\x7f]')


def css_quoted(value: str) -> str:
    """A quote, backslash or newline would otherwise end the string and select something else."""
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
    return CSS_UNSAFE.sub(r"\\\1", value)


def generated_id(value: str) -> bool:
    return any(c.isdigit() for c in value) or len(value) > 40


def href_prefix(href: str) -> str | None:
    """A trailing segment carrying a number is the page; the rest is the section, or ``None``."""
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
    """The candidate descends from an ancestor's test id; ``:is()`` keeps the tail's specificity out."""
    attribute = f"[{locators.testid_attribute}={css_quoted(locators.testid or '')}]"
    if not locators.testid_depth:
        return attribute
    return f"{attribute} :is({locators.tag})"


def candidate_selectors(locators: Locators, *, role_selectors: bool) -> list[str]:
    """Ranked by what survives a redeploy, one per kind; ``role=`` only for drivers that parse it."""
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
