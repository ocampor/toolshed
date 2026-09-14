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


def explore_limits() -> dict[str, object]:
    """Every limit and vocabulary the per-element read applies, so
    ``FirstMatch.why_not`` and the JS agree on one list of names."""
    return {
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


def with_explore_element(source: str) -> str:
    """``source`` with the shared per-element read and its limits filled in."""
    return source.replace(
        constants.EXPLORE_ELEMENT_PLACEHOLDER, load_script("explore_element")
    ).replace(constants.EXPLORE_LIMITS_PLACEHOLDER, json.dumps(explore_limits()))


def explore_first_js() -> str:
    """``async (el) => ExploreRead`` — what one element is right now."""
    return with_explore_element(load_script("explore_first"))


def explore_many_js(
    targets: list[dict[str, object]],
    sample: int,
    sample_chars: int,
    timeout_ms: int,
) -> str:
    """``async (el) => list[ExploreManyRead]`` — every target in one page call.

    ``targets`` carry the CSS selector and the already-resolved extract spec,
    so the page side reads the same field names ``Driver.read_field`` would.
    """
    batch = {
        "targets": targets,
        "sample": sample,
        "sample_chars": sample_chars,
        "timeout_ms": timeout_ms,
        "poll_ms": constants.EXPLORE_MANY_POLL_MS,
        "properties": list(constants.EXTRACT_PROPERTIES),
    }
    return with_explore_element(load_script("explore_many")).replace(
        constants.EXPLORE_BATCH_PLACEHOLDER, json.dumps(batch)
    )


def survey_js() -> str:
    """``(el) => SurveyRead`` — the page's named elements, links and repeats."""
    limits = {
        "text_max": constants.SURVEY_TEXT_MAX_CHARS,
        "testid_attributes": list(constants.TESTID_ATTRIBUTES),
        "max_raw_landmarks": constants.SURVEY_MAX_RAW_LANDMARKS,
        "max_raw_repeats": constants.SURVEY_MAX_RAW_REPEATS,
        "max_hrefs": constants.SURVEY_MAX_HREFS,
        "min_siblings": constants.SURVEY_MIN_SIBLINGS,
        "class_suffix": constants.CLASS_SUFFIX_PATTERN,
        "max_nested_controls": constants.EXPLORE_MAX_NESTED_CONTROLS,
        "nested_text_max": constants.EXPLORE_NESTED_TEXT_MAX_CHARS,
    }
    return load_script("survey").replace(
        constants.SURVEY_LIMITS_PLACEHOLDER, json.dumps(limits)
    )


def count_selectors_js(selectors: list[str]) -> str:
    """``(el) => {selector: count}`` — what each selector matches page-wide.

    The selectors ``survey`` reports are built in Python, so the page is asked
    about them in a second call; one it cannot parse counts as zero.
    """
    return load_script("count_selectors").replace(
        constants.SURVEY_COUNT_PLACEHOLDER, json.dumps(selectors)
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
