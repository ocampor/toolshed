"""Run flows stored as YAML files — the path-based layer over the
in-memory core in :mod:`llm_browser.flows`."""

from collections.abc import Iterable
from pathlib import Path

import yaml

from llm_browser.flows import SelectorMap, run_flow
from llm_browser.models import Flow, FlowError, FlowResult
from llm_browser.session import BrowserSession


def load_flow(
    flow_path: str | Path,
    *,
    selector_map: SelectorMap | None = None,
) -> Flow:
    """Load a flow YAML, resolve every ``run-flow`` reference, and
    expand selector-map ``ref:``s — all inside one
    ``Flow.model_validate`` call.

    The validation context carries:

    - ``base_dir`` so ``RunFlowStep``'s after-validator can read each
      referenced child YAML and attach it as ``step.subflow``.
    - ``selector_map`` so ``BaseStep``'s before-validator can replace
      ``ref: <key>`` with ``selector: <map[key]>`` before pydantic
      checks the model shape. Strict: an unknown ref raises a
      ``ValidationError`` at this point, not a "selector required"
      cascade later.

    Missing files, malformed YAML, sub-flow constraint violations,
    unknown refs — every load-time error surfaces from this call.
    """
    path = Path(flow_path).resolve()
    return Flow.model_validate(
        yaml.safe_load(path.read_text()),
        context={"base_dir": path.parent, "selector_map": selector_map},
    )


def run_flow_file(
    session: BrowserSession,
    flow_path: str | Path,
    data: dict[str, object],
    *,
    selector_map: SelectorMap | None = None,
    from_step: str | None = None,
    redact: Iterable[str] = (),
) -> FlowResult:
    """:func:`load_flow` then :func:`llm_browser.flows.run_flow`, with
    ``RetryHint.flow_path`` pointing back at ``flow_path`` so the caller
    can re-run the same file.

    ``selector_map`` is the loaded selector-map dict (call
    :func:`llm_browser.selector_map.load_selector_map` once at the CLI
    layer and pass it through); refs in every step, sub-flow children
    included, are resolved while loading. ``from_step`` and ``redact``
    are handed straight to the runner.
    """
    path = Path(flow_path).resolve()
    flow = load_flow(path, selector_map=selector_map)
    result = run_flow(session, flow, data, from_step=from_step, redact=redact)
    return with_flow_path(result, str(path))


def with_flow_path(result: FlowResult, flow_path: str) -> FlowResult:
    """Return ``result`` with its retry hint pointing at ``flow_path``."""
    if not isinstance(result, FlowError) or result.retry_hint is None:
        return result
    hint = result.retry_hint.model_copy(update={"flow_path": flow_path})
    return result.model_copy(update={"retry_hint": hint})
