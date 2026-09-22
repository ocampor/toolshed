"""The models read off themselves — the generated reference is only as
complete as this is."""

from llm_browser.introspect import own_fields, session_methods, step_arms
from llm_browser.models import BaseStep, ClickStep

STEP_ARM_COUNT = 18


def test_every_union_arm_is_reported_under_its_action_tag() -> None:
    arms = dict(step_arms())
    assert len(arms) == STEP_ARM_COUNT
    assert {"click", "goto", "run-flow", "eval", "wait_for"} <= set(arms)
    assert arms["click"] is ClickStep


def test_own_fields_excludes_the_discriminator_and_the_shared_options() -> None:
    fields = own_fields(ClickStep)
    assert "dispatch" in fields
    assert "selector" in fields
    assert "action" not in fields
    assert not set(fields) & set(BaseStep.model_fields)


def test_session_methods_are_public_and_sorted() -> None:
    names = session_methods()
    assert names == sorted(names)
    assert "find_all" in names
    assert not [name for name in names if name.startswith("_")]
