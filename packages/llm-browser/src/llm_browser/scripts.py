"""In-page JavaScript loaded from ``js/``."""

import json
from functools import lru_cache
from pathlib import Path

from llm_browser import constants

JS_DIR = Path(__file__).parent / "js"


@lru_cache(maxsize=None)
def load_script(name: str) -> str:
    """Return the source of ``js/<name>.js``."""
    return (JS_DIR / f"{name}.js").read_text()


def extract_rows_js() -> str:
    """``(rows, spec) => list[dict]`` — read every field off every row.

    The property allowlist is substituted in so the page-side rule and
    ``Driver.read_field`` read the same names."""
    return load_script("extract_rows").replace(
        constants.EXTRACT_PROPERTIES_PLACEHOLDER,
        json.dumps(list(constants.EXTRACT_PROPERTIES)),
    )


def explore_first_js() -> str:
    """``async (el) => {first, candidates}`` — what one element is right now.

    Every limit and vocabulary the page side applies is substituted in, so
    ``FirstMatch.why_not`` and the JS agree on one list of names."""
    limits = {
        "text_max": constants.EXPLORE_TEXT_MAX_CHARS,
        "cover_text_max": constants.EXPLORE_COVER_TEXT_MAX_CHARS,
        "stable_delay_ms": constants.EXPLORE_STABLE_DELAY_MS,
        "interactive_tags": list(constants.INTERACTIVE_TAGS),
        "interactive_roles": list(constants.INTERACTIVE_ROLES),
        "implicit_roles": constants.IMPLICIT_ROLES,
        "nested_text_max": constants.EXPLORE_NESTED_TEXT_MAX_CHARS,
        "max_nested_controls": constants.EXPLORE_MAX_NESTED_CONTROLS,
        "ancestor_levels": constants.EXPLORE_ANCESTOR_LEVELS,
        "testid_attributes": list(constants.TESTID_ATTRIBUTES),
    }
    return load_script("explore_first").replace(
        constants.EXPLORE_LIMITS_PLACEHOLDER, json.dumps(limits)
    )


def select_option_js(value: str) -> str:
    """``(el) => "ok"`` or one of the ``SELECT_FAILURES`` keys, for one value."""
    return load_script("select_option").replace(
        constants.SELECT_VALUE_PLACEHOLDER, json.dumps(value)
    )


def select_control_tag_js() -> str:
    """``(el) => tagName`` — of the labelled control, if ``el`` is a label."""
    return load_script("select_control_tag")


def page_probe_js(selector: str | None, max_chars: int) -> str:
    """``() => PageProbe`` — password/challenge visibility plus page text.

    Drivers evaluate a bare script string with no arguments, so the selector,
    the shared challenge-selector list and the text limit are substituted in.
    """
    challenge = ", ".join(constants.CHALLENGE_SELECTORS)
    return (
        load_script("page_probe")
        .replace(constants.PROBE_SELECTOR_PLACEHOLDER, json.dumps(selector))
        .replace(
            constants.PROBE_PASSWORD_PLACEHOLDER,
            json.dumps(constants.PASSWORD_SELECTOR),
        )
        .replace(constants.PROBE_CHALLENGE_PLACEHOLDER, json.dumps(challenge))
        .replace(constants.PROBE_MAX_CHARS_PLACEHOLDER, str(max_chars))
    )
