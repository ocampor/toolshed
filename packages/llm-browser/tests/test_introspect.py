"""The models read off themselves — the generated reference is only as
complete as this is."""

import inspect

from llm_browser.introspect import own_fields, session_methods, step_arms
from llm_browser.models import BaseStep, ClickStep
from llm_browser.session import BrowserSession

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


def test_every_step_field_and_option_carries_a_description() -> None:
    """The generated reference is built from these, so a field shipped without
    one would document itself as a blank cell."""
    missing = [
        f"{action}.{name}"
        for action, step_class in step_arms()
        for name in own_fields(step_class)
        if not (step_class.model_fields[name].description or "").strip()
    ] + [
        f"BaseStep.{name}"
        for name, field in BaseStep.model_fields.items()
        if not (field.description or "").strip()
    ]
    assert missing == []


def test_every_step_type_explains_itself() -> None:
    assert [
        action for action, step_class in step_arms() if not step_class.__doc__
    ] == []


def test_every_session_member_explains_itself() -> None:
    """`reference/session.md` is those docstrings; a missing one is a blank
    section in the shipped docs."""
    undocumented = [
        name
        for name in session_methods()
        if not inspect.getdoc(getattr(BrowserSession, name))
    ]
    assert undocumented == []
