"""The reference and the conformance suite both ask these, so a new step type shows up in both."""

import functools
import inspect
import typing

from llm_browser.models import BaseStep, Step
from llm_browser.session import BrowserSession


def step_arms() -> list[tuple[str, type[BaseStep]]]:
    """The tag is the string a flow writes as ``action:``, including ``eval``."""
    union = typing.get_args(Step)[0]
    arms = []
    for arm in typing.get_args(union):
        step_class, tag = typing.get_args(arm)
        arms.append((str(tag.tag), step_class))
    return sorted(arms)


def own_fields(step_class: type[BaseStep]) -> list[str]:
    """``action`` is the discriminator and ``BaseStep`` fields count once as options.
    Misses a step that re-declares a ``BaseStep`` option: the subtraction goes by name.
    """
    return [
        name
        for name in step_class.model_fields
        if name != "action" and name not in BaseStep.model_fields
    ]


def session_methods() -> list[str]:
    """Walks the MRO: a ``property`` or ``classmethod`` is not a function after the class body."""
    descriptors = (staticmethod, classmethod, property, functools.cached_property)
    names = set()
    for klass in BrowserSession.__mro__:
        for name, member in vars(klass).items():
            if name.startswith("_"):
                continue
            if inspect.isfunction(member) or isinstance(member, descriptors):
                names.add(name)
    return sorted(names)
