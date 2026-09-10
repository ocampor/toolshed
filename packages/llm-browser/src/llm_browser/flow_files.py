"""Path-based layer over the in-memory core in :mod:`llm_browser.flows`."""

from collections.abc import Iterable
from pathlib import Path

from llm_browser.flow_pipeline import FlowSource, SelectorMap, build_flow
from llm_browser.flows import run_flow
from llm_browser.models import Flow, FlowError, FlowResult
from llm_browser.session import BrowserSession


def load_flow(
    flow_path: str | Path,
    *,
    selector_map: SelectorMap | None = None,
) -> Flow:
    """``build_flow`` over a path source; see :mod:`llm_browser.flow_pipeline`.
    Every load-time error — missing file, bad text, unknown ref, illegal
    sub-flow — surfaces from this one call."""
    return build_flow(FlowSource.from_path(flow_path), selector_map=selector_map)


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
