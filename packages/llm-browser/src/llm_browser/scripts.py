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
    """``(rows, spec) => list[dict]`` — read every field off every row."""
    return load_script("extract_rows")


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
