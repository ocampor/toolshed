"""Step execution: resolve templates, evaluate conditions, dispatch actions."""

import logging
import time
from typing import Any, cast

from yaml_engine.compile import compile_condition
from yaml_engine.conditions import evaluate_condition
from yaml_engine.template import resolve_templates_in_dict

from llm_browser.actions import execute_action
from llm_browser.behavior import Behavior
from llm_browser.results import ActionResult, SkippedResult
from llm_browser.constants import LOGGER_NAME, WHEN_SKIP_REASON
from llm_browser.models import FlowData, FlowError, Step, validate_step
from llm_browser.probe import human_needed
from llm_browser.repeat import ElementScope
from llm_browser.selector_map import SelectorMap, resolve_step_refs
from llm_browser.selectors import ScopedSelector, parse_selector
from llm_browser.session import BrowserSession

logger = logging.getLogger(LOGGER_NAME)


def should_skip(session: BrowserSession, step: Step, data: FlowData) -> bool:
    """Return True if the step's when clause is not satisfied.

    Supported predicates:
      * ``element_exists``  — skip unless the element is present.
      * ``element_missing`` — skip unless the element is absent
        (idempotent toggles: only click when the post-click element
        isn't already there).
      * ``text_present``   — skip unless the page renders that text,
        optionally scoped to ``selector`` and ``exact``.
      * Plain field/op/value forms compiled by ``yaml_engine``.
    """
    if not step.when:
        return False
    template_dict = data.to_template_dict()
    for raw_cond in step.when:
        if "element_exists" in raw_cond:
            spec = raw_cond["element_exists"]
            selector = parse_selector(spec["selector"])
            if not session.element_exists(selector):
                return True
        elif "element_missing" in raw_cond:
            spec = raw_cond["element_missing"]
            selector = parse_selector(spec["selector"])
            if session.element_exists(selector):
                return True
        elif "text_present" in raw_cond:
            spec = raw_cond["text_present"]
            scope = spec.get("selector")
            if not session.text_present(
                spec["text"],
                selector=parse_selector(scope) if scope is not None else None,
                exact=bool(spec.get("exact", False)),
            ):
                return True
        else:
            cond = compile_condition(raw_cond)
            value = template_dict.get(cond.field)
            if not evaluate_condition(cond.op, value, cond.param):
                return True
    return False


def resolve_step_templates(step: Step, data: FlowData) -> Step:
    """Resolve {{ template }} refs inside ``step`` against ``data`` and
    return a freshly-validated Step, its ``ref:`` selectors untouched.
    Idempotent — resolving a resolved step is a no-op. Carries ``_parent``
    (a private attr set during flow load) across the round trip so qualified
    names survive.

    A ``run-flow`` step's child body is left untemplated: the child resolves
    its own steps against its own data, so a parent param never substitutes a
    name the step's ``data:`` binds.
    """
    raw = step.model_dump(exclude_none=True)
    child_flow = raw.pop("flow", None)
    resolved_raw = resolve_templates_in_dict(raw, data.to_template_dict())
    if child_flow is not None:
        resolved_raw["flow"] = child_flow
    resolved = validate_step(resolved_raw)
    resolved._parent = step._parent
    return resolved


def resolve_step(
    step: Step,
    data: FlowData,
    selector_map: SelectorMap | None = None,
    scope: ElementScope | None = None,
) -> Step:
    """A step ready to execute: templates resolved, every ``ref:`` selector
    swapped for the one ``selector_map`` carries, and an ``in:`` step's
    selector scoped to ``scope``'s element. A ref the map lacks raises
    :class:`~llm_browser.selector_map.MissingSelectorsError`."""
    resolved = resolve_step_templates(step, data)
    resolve_step_refs(resolved, selector_map)
    if resolved.scope is not None and scope is not None:
        # After the refs, so a `ref:` selector scopes like anything else.
        target = cast(Any, resolved)
        target.selector = ScopedSelector(
            root=scope.root, index=scope.index, inner=target.selector
        )
    return resolved


def page_needs_human(session: BrowserSession) -> bool:
    """Whether the failing page is asking for a login or a challenge.

    Diagnostic only: a probe that itself fails must never replace the error
    the caller actually cares about.
    """
    try:
        return human_needed(session.probe())
    except Exception:
        logger.debug("probe failed while diagnosing a step failure", exc_info=True)
        return False


def execute_step(
    session: BrowserSession,
    step: Step,
    data: FlowData,
    behavior: Behavior | None = None,
    selector_map: SelectorMap | None = None,
    scope: ElementScope | None = None,
) -> ActionResult | FlowError:
    """A ``when:``-skipped step returns a ``SkippedResult``, not a failure.
    ``RunFlowStep`` never reaches here — ``run_loaded_flow`` dispatches it.
    ``behavior`` is the run's default, which the step's own ``humanize``
    refines; ``scope`` is the element an ``in:`` step is confined to."""
    resolved = resolve_step(step, data, selector_map, scope)
    if should_skip(session, resolved, data):
        return SkippedResult(reason=WHEN_SKIP_REASON)
    action_result = execute_action(session, resolved, behavior)
    if not action_result.ok:
        capture = session.capture
        return FlowError(
            step=resolved.qualified_name,
            data=action_result,
            screenshot=(
                session.screenshot_bytes()
                if capture in ("screenshot", "both")
                else None
            ),
            dom=session.dom_snapshot() if capture in ("dom", "both") else None,
            human_needed=page_needs_human(session),
        )
    if resolved.eval:
        session.evaluate(session.get_page(), resolved.eval)
    if resolved.wait_after:
        time.sleep(resolved.wait_after / 1000)
    return action_result
