"""Heuristic for spotting a page that genuinely needs a human at the keyboard."""

import re
import unicodedata

from llm_browser import probe_constants
from llm_browser.models import PageProbe


def has_challenge_markup(markup: str) -> bool:
    if re.search(probe_constants.CHALLENGE_IFRAME_PATTERN, markup) is not None:
        return True
    return any(marker in markup for marker in probe_constants.CHALLENGE_MARKERS)


def has_interstitial_phrase(text: str) -> bool:
    folded = fold_text(text)
    return any(phrase in folded for phrase in probe_constants.INTERSTITIAL_PHRASES)


def fold_text(text: str) -> str:
    """Case- and accent-insensitive form: ``Mantén`` and ``manten`` compare equal."""
    decomposed = unicodedata.normalize("NFKD", text)
    bare = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return bare.casefold()


def probe_from_markup(markup: str) -> PageProbe:
    """A failure snapshot is static markup, so presence has to stand in for visibility."""
    folded = fold_text(markup)
    return PageProbe(
        password_visible=re.search(probe_constants.PASSWORD_INPUT_PATTERN, folded)
        is not None,
        challenge=has_challenge_markup(folded),
        text=markup,
    )


def human_needed(probe: PageProbe) -> bool:
    return bool(
        probe.password_visible or probe.challenge or has_interstitial_phrase(probe.text)
    )
