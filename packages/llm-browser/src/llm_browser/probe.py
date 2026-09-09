"""Heuristic for spotting a page that genuinely needs a human at the keyboard."""

import re

from llm_browser import constants
from llm_browser.models import PageProbe


def has_challenge_markup(markup: str) -> bool:
    if re.search(constants.CHALLENGE_IFRAME_PATTERN, markup) is not None:
        return True
    return any(marker in markup for marker in constants.CHALLENGE_MARKERS)


def has_interstitial_phrase(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in constants.INTERSTITIAL_PHRASES)


def probe_from_markup(markup: str) -> PageProbe:
    """A failure snapshot is static markup, so presence has to stand in for visibility."""
    lowered = markup.lower()
    return PageProbe(
        password_visible=re.search(constants.PASSWORD_INPUT_PATTERN, lowered)
        is not None,
        challenge=has_challenge_markup(lowered),
        text=markup,
    )


def human_needed(probe: PageProbe) -> bool:
    return bool(
        probe.password_visible or probe.challenge or has_interstitial_phrase(probe.text)
    )
