"""The library read off itself: step arms, their own fields, session members.

Everything that documents or checks the library — the generated reference in
:mod:`llm_browser.docgen`, the conformance suite's required set — asks these
three functions rather than keeping its own list, so a step type or a field
added to the models shows up in both on the day it lands.
"""

import functools
import inspect
import typing

from llm_browser.models import BaseStep, Step
from llm_browser.session import BrowserSession


def step_arms() -> list[tuple[str, type[BaseStep]]]:
    """``(action tag, step class)`` for every arm of the ``Step`` union.

    The union is ``Annotated[A | B | ..., Discriminator]`` and each arm is
    ``Annotated[StepClass, Tag("action")]``, so the tag is the same string a
    flow writes as ``action:`` — including ``eval``, which has none.
    """
    union = typing.get_args(Step)[0]
    arms = []
    for arm in typing.get_args(union):
        step_class, tag = typing.get_args(arm)
        arms.append((str(tag.tag), step_class))
    return sorted(arms)


def own_fields(step_class: type[BaseStep]) -> list[str]:
    """Fields this step has below ``BaseStep``.

    ``action`` is the discriminator, not an option, and the ``BaseStep``
    fields are counted once as options rather than once per step type.
    Everything under it is per-step, ``SelectorStep.selector`` included: what
    a selector means is the step's own question, so every selector step keeps
    the row.

    The one thing this misses is a step that re-declares a ``BaseStep``
    option to narrow it: the subtraction goes by name, not by semantics.
    """
    return [
        name
        for name in step_class.model_fields
        if name != "action" and name not in BaseStep.model_fields
    ]


def session_methods() -> list[str]:
    """Every public member of ``BrowserSession``, however it is declared.

    Walking the MRO rather than ``inspect.getmembers``: a ``property`` or a
    ``classmethod`` is not a function once the class body is done with it, so
    a session attribute declared as one would otherwise never be required.
    """
    descriptors = (staticmethod, classmethod, property, functools.cached_property)
    names = set()
    for klass in BrowserSession.__mro__:
        for name, member in vars(klass).items():
            if name.startswith("_"):
                continue
            if inspect.isfunction(member) or isinstance(member, descriptors):
                names.add(name)
    return sorted(names)
