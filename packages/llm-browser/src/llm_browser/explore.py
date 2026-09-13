"""The two rules ``BrowserSession.explore`` answers with: verdict and stability."""

import re
from collections.abc import Callable

from llm_browser.models import FirstMatch, Intent, Stability, Verdict

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
