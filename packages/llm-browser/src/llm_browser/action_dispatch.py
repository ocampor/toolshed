"""Dispatch one step: resolve its behaviour, run its handler, shape the failure.

The handlers themselves live in :mod:`llm_browser.actions`, which is also what
registers them — import that module, not this one, to run a step.
"""

from functools import lru_cache
from typing import Callable

from yaml_engine.registry import Registry

from llm_browser.behavior import Behavior, paced
from llm_browser.models import Step, match_rule_of
from llm_browser.results import (
    AcceptedMatch,
    ActionResult,
    ErrorResult,
    SkippedResult,
    VoidResult,
    is_step_failure,
    is_timeout,
)
from llm_browser.selectors import MatchError
from llm_browser.session import BrowserSession
from llm_browser.session_input import behavior_for, with_driver_opt_outs

# Param type is loose because each handler accepts a specific Step subclass, and
# Callable parameters are contravariant. The discriminated Step union dispatches
# at runtime via the registry, so this widening only affects static typing.
ActionHandler = Callable[..., ActionResult]


@lru_cache(maxsize=1)
def get_registry() -> Registry[ActionHandler]:
    return Registry("action")


def step_behavior(
    session: BrowserSession, step: Step, run_behavior: Behavior | None
) -> Behavior:
    """What this step runs under: the run's default when it has one, the
    session's otherwise, with the step's own ``humanize`` switched into it and
    the driver's opt-outs applied last.

    Resolved once, here, so the pacing around the action and the input call
    inside it are the same behaviour, and so a run-level default reaches a
    step without anything on the session changing.
    """
    base = run_behavior if run_behavior is not None else session.behavior
    stepped = behavior_for(base, getattr(step, "humanize", None))
    return with_driver_opt_outs(session.behavior, stepped)


def execute_action(
    session: BrowserSession, step: Step, behavior: Behavior | None = None
) -> ActionResult:
    """``behavior`` is the run-level default; a step's ``humanize`` refines it."""
    if step.action is None:
        return VoidResult()
    resolved = step_behavior(session, step, behavior)
    # Bound before the action runs so a failing step still reports the mismatch
    # its pick accepted on the way in.
    accepted: list[AcceptedMatch] = []
    try:
        with paced(resolved), session.matching(match_rule_of(step)) as accepted:
            result = get_registry().get(step.action)(session, step, resolved)
        # One action, one warning: a step that found its element twice
        # accepted the same mismatch twice.
        return (
            result.model_copy(update={"accepted": accepted[0]}) if accepted else result
        )
    except Exception as exc:
        if not is_step_failure(exc):
            raise
        first = accepted[0] if accepted else None
        if step.optional:
            return SkippedResult(
                reason=f"{type(exc).__name__}: {str(exc)[:200]}", accepted=first
            )
        return failure_result(step, exc, first)


def failure_result(
    step: Step, exc: BaseException, accepted: AcceptedMatch | None = None
) -> ErrorResult:
    selector = getattr(step, "selector", None)
    matched = exc if isinstance(exc, MatchError) else None
    hint = None
    if matched is not None:
        hint = matched.hint
    elif is_timeout(exc):
        hint = "element hidden, missing, or slow to render"
    return ErrorResult(
        error=type(exc).__name__,
        # Collapse whitespace so multi-line errors (Pydantic ValidationError,
        # patchright tracebacks) survive the 300-char cap meaningfully.
        message=" ".join(str(exc).split())[:300],
        step_name=step.name,
        selector=repr(selector) if selector is not None else None,
        hint=hint,
        expected=matched.expected if matched else None,
        found=matched.found if matched else None,
        samples=matched.samples if matched else None,
        accepted=accepted,
    )
