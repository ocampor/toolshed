"""Path-based layer over the in-memory core in :mod:`llm_browser.flows`."""

from collections.abc import Iterable
from pathlib import Path

from llm_browser.flows import SelectorMap, parse_flow_yaml, run_flow
from llm_browser.models import Flow, FlowError, FlowResult
from llm_browser.session import BrowserSession


def load_flow(
    flow_path: str | Path,
    *,
    selector_map: SelectorMap | None = None,
) -> Flow:
    """Every load-time error — missing file, bad YAML, unknown ref, illegal
    sub-flow — surfaces from this one ``model_validate`` call."""
    path = Path(flow_path).resolve()
    return Flow.model_validate(
        parse_flow_yaml(path.read_text()),
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
    ``RetryHint.flow_path`` filled in from ``flow_path``."""
    path = Path(flow_path).resolve()
    flow = load_flow(path, selector_map=selector_map)
    result = run_flow(session, flow, data, from_step=from_step, redact=redact)
    return with_flow_path(result, str(path))


def with_flow_path(result: FlowResult, flow_path: str) -> FlowResult:
    if not isinstance(result, FlowError) or result.retry_hint is None:
        return result
    hint = result.retry_hint.model_copy(update={"flow_path": flow_path})
    return result.model_copy(update={"retry_hint": hint})
