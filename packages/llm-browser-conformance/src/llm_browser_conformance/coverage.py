"""What the suite covers, read off the library rather than off a list.

``docs/coverage.md`` is this module's output. The point is the *required* set:
the step types, step fields, step options and session methods are introspected
from ``llm_browser`` itself, so a step type the library grows — or a field
added to an existing one — turns into an uncovered row and fails
``tests/test_coverage.py`` until a scenario claims it.

A scenario claims a key through ``Scenario.covers``. Keys are strings with a
kind prefix:

| key | means |
| --- | --- |
| ``step:click`` | the ``click`` step type |
| ``field:goto.wait_until`` | a field declared by one step type |
| ``option:optional`` | a ``BaseStep`` field, i.e. an option every step has |
| ``when:eq`` | a ``when:`` condition |
| ``session:find_all`` | a public ``BrowserSession`` member |
| ``api:redact`` | library surface that is not a model field or a method |

Only ``api:`` keys are hand-listed, because there is nothing to introspect:
they name behaviour (``redact=``, partial outputs, a sanitize level) rather
than an attribute.
"""

import functools
import inspect
import typing
from collections.abc import Iterable

from llm_browser.models import BaseStep, Step
from llm_browser.session import BrowserSession

from llm_browser_conformance.scenarios import ALL_SCENARIOS

# The two predicates ``llm_browser.steps.should_skip`` implements itself, plus
# the ``yaml_engine`` operators a flow author reaches for first. The operator
# registry is yaml-engine's surface, not llm-browser's, so it is not the whole
# registry — these are the ones the library's own docs teach.
REQUIRED_CONDITIONS = (
    "element_exists",
    "element_missing",
    "eq",
    "is_truthy",
    "not_null",
)

# Behaviour with no field or method to introspect. Each one is a promise the
# library makes in prose; a scenario has to be the thing that keeps it true.
REQUIRED_API = (
    "behavior.human",
    "behavior.off",
    "capture_level",
    "cli.capture_dir",
    "cli.out_dir",
    "cli.typed_rows",
    "error.outputs",
    "flow_repository",
    "from_step",
    "goto.scheme_guard",
    "human_needed.challenge",
    "human_needed.password",
    "outputs.json",
    "outputs.qualified_name",
    "outputs.shape",
    "params.default",
    "params.required",
    "redact",
    "retry_hint",
    "sanitize.high",
    "sanitize.low",
    "sanitize.medium",
    "sanitize.xhigh",
    "templating.selector",
    "templating.value",
    "type.delay_jitter",
)


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


def required_keys() -> dict[str, list[str]]:
    """Every key a scenario must claim, grouped by the section it appears in."""
    arms = step_arms()
    return {
        "step types": [f"step:{action}" for action, _ in arms],
        "step fields": [
            f"field:{action}.{field}"
            for action, step_class in arms
            for field in own_fields(step_class)
        ],
        "step options": [f"option:{name}" for name in BaseStep.model_fields],
        "when conditions": [f"when:{name}" for name in REQUIRED_CONDITIONS],
        "session methods": [f"session:{name}" for name in session_methods()],
        "library behaviour": [f"api:{name}" for name in REQUIRED_API],
    }


def every_required_key() -> set[str]:
    return {key for group in required_keys().values() for key in group}


def claimed_keys() -> dict[str, list[str]]:
    """Key to the scenarios claiming it, in scenario order."""
    claims: dict[str, list[str]] = {}
    for scenario in ALL_SCENARIOS:
        for key in sorted(scenario.covers):
            claims.setdefault(key, []).append(scenario.name)
    return claims


def uncovered() -> list[str]:
    claims = claimed_keys()
    return sorted(key for key in every_required_key() if key not in claims)


def unknown() -> list[str]:
    """Claimed keys that nothing requires — almost always a typo."""
    required = every_required_key()
    return sorted(key for key in claimed_keys() if key not in required)


# --- The document ---

HEADER = """<!-- Generated by `llm-browser-check --coverage`; edit the scenarios, not this file. -->

# Coverage

Every step type, step field, step option, `when:` condition and
`BrowserSession` method the library exposes, and the scenarios that exercise
it. The rows are introspected from `llm_browser.models` and
`llm_browser.session`, so a step type or field added to the library shows up
here uncovered, and `tests/test_coverage.py` fails until a scenario claims it.

A scenario claims a key through `Scenario.covers`; see
`src/llm_browser_conformance/coverage.py` for the key grammar.
"""


def table(keys: Iterable[str], claims: dict[str, list[str]]) -> str:
    rows = "".join(
        f"| `{key}` | {', '.join(claims.get(key, [])) or '**uncovered**'} |\n"
        for key in keys
    )
    return f"| item | scenarios |\n| --- | --- |\n{rows}"


def coverage_document() -> str:
    claims = claimed_keys()
    sections = [
        f"\n## {title}\n\n{table(keys, claims)}"
        for title, keys in required_keys().items()
    ]
    return HEADER + "".join(sections)
