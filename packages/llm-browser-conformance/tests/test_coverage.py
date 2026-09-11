"""The suite has to notice when the library grows something it does not check.

``docs/known-gaps.md`` says what is broken; this says what is *unexamined*,
which is the more dangerous of the two. The required rows are introspected
from ``llm_browser`` itself, so a new step type, a new field on an existing
step, or a new ``BrowserSession`` method fails here on the day it lands —
before anyone can call a release "acceptance tested" on a suite that never
touched it.
"""

from pathlib import Path

import pytest
from llm_browser.session import BrowserSession

from llm_browser_conformance.coverage import (
    REQUIRED_API,
    REQUIRED_CONDITIONS,
    claimed_keys,
    coverage_document,
    every_required_key,
    own_fields,
    required_keys,
    session_methods,
    step_arms,
    uncovered,
    unknown,
)

PACKAGE_DIR = Path(__file__).resolve().parent.parent
COVERAGE = PACKAGE_DIR / "docs" / "coverage.md"


def test_every_public_step_option_and_method_has_a_scenario() -> None:
    assert uncovered() == [], (
        "nothing in the suite exercises these; add a scenario and claim the "
        "key in its `covers`"
    )


def test_no_scenario_claims_a_key_nothing_requires() -> None:
    assert unknown() == [], (
        "claimed but not in the required set — a typo, or a key that outlived what it named"
    )


def test_the_coverage_table_matches_the_scenarios() -> None:
    assert COVERAGE.read_text() == coverage_document(), (
        "docs/coverage.md is stale; regenerate with "
        "`uv run llm-browser-check --coverage > docs/coverage.md`"
    )


def test_the_required_set_is_read_off_the_library() -> None:
    """Guards the introspection itself: a `required_keys` that silently
    returned nothing would make every assertion above vacuous."""
    groups = required_keys()
    actions = {action for action, _ in step_arms()}
    assert {"click", "goto", "run-flow", "eval"} <= actions
    assert groups["step types"] == [f"step:{a}" for a in sorted(actions)]
    assert "field:goto.wait_until" in groups["step fields"]
    assert "option:optional" in groups["step options"]
    assert "session:find_all" in groups["session methods"]
    assert len(every_required_key()) == sum(len(g) for g in groups.values())


def test_the_discriminator_is_not_mistaken_for_an_option() -> None:
    """``action`` is how a step is chosen, not something to exercise, and the
    ``BaseStep`` fields are counted once as options rather than per step."""
    for _, step_class in step_arms():
        assert "action" not in own_fields(step_class)
        assert "optional" not in own_fields(step_class)


def test_private_session_helpers_are_not_required() -> None:
    assert not [name for name in session_methods() if name.startswith("_")]


def test_a_session_property_is_required_like_a_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``inspect.isfunction`` sees neither a ``property`` nor a
    ``classmethod``, so a session attribute declared as one would slip past
    the gate the day the library grows it."""
    monkeypatch.setattr(
        BrowserSession, "brand_prop", property(lambda self: None), raising=False
    )
    assert "brand_prop" in session_methods()
    assert "session:brand_prop" in uncovered()


def test_the_hand_listed_keys_stay_sorted_and_unique() -> None:
    """They are the only rows nothing introspects, so drift shows up here."""
    for names in (REQUIRED_API, REQUIRED_CONDITIONS):
        assert list(names) == sorted(set(names))


def test_the_table_names_the_scenario_behind_each_row() -> None:
    document = coverage_document()
    for key, scenarios in claimed_keys().items():
        if key in every_required_key():
            assert f"`{key}`" in document
            assert scenarios[0] in document
