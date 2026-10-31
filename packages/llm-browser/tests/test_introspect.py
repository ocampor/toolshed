import inspect
import typing

from llm_browser.behavior import BehaviorProfile
from llm_browser.cli import BEHAVIOR_PRESETS
from llm_browser.introspect import session_methods, step_arms
from llm_browser.models import TEXT_STATES, WAIT_STATES, WaitState
from llm_browser.session import BrowserSession


def test_every_step_type_explains_itself() -> None:
    assert [
        action for action, step_class in step_arms() if not step_class.__doc__
    ] == []


def test_every_session_member_explains_itself() -> None:
    undocumented = [
        name
        for name in session_methods()
        if not inspect.getdoc(getattr(BrowserSession, name))
    ]
    assert undocumented == []


def test_wait_states_are_bound_to_the_literal() -> None:
    states = set(typing.get_args(WaitState))
    assert set(WAIT_STATES) == states
    assert set(TEXT_STATES) <= states


def test_behaviour_presets_are_bound_to_the_profile() -> None:
    assert set(BEHAVIOR_PRESETS) | {"custom"} == set(typing.get_args(BehaviorProfile))
