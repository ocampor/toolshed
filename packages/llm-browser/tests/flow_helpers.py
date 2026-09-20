"""Resolve → load → run, the three stages a file-backed flow test needs."""

import asyncio
from collections.abc import Iterable
from pathlib import Path
from unittest.mock import MagicMock

from llm_browser.flow_pipeline import resolve_flow
from llm_browser.flow_repository import FileFlowRepository
from llm_browser.flows import load_flow_document, run_flow, with_flow_path
from llm_browser.models import Flow, FlowResult


def load_flow_file(path: str | Path) -> Flow:
    flow_path = Path(path)
    repo = FileFlowRepository(flow_path.parent)
    return load_flow_document(asyncio.run(resolve_flow(flow_path.name, repo)))


def run_flow_file(
    session: MagicMock,
    path: str | Path,
    data: dict[str, object],
    *,
    from_step: str | None = None,
    redact: Iterable[str] = (),
) -> FlowResult:
    flow = load_flow_file(path)
    result = run_flow(session, flow, data, from_step=from_step, redact=redact)
    return with_flow_path(result, str(Path(path).resolve()))


def stub_matching(session: MagicMock) -> MagicMock:
    """``BrowserSession.matching`` is a context manager yielding the mismatches
    a step accepted; a bare mock yields a truthy mock instead of a list."""
    session.matching.return_value.__enter__.return_value = []
    return session
