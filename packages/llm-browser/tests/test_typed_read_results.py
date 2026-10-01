"""Typed-read errors and the parse deprecation reach the flow result."""

import logging

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from llm_browser.constants import PARSE_DEPRECATED
from llm_browser.flows import load_flow_document, run_flow
from llm_browser.models import FlowSuccess
from llm_browser.results import ExtractError

FAILED = ExtractError(
    row=0, field="n", msg="Value error, could not convert 'x' to int", input="x"
)
READ = {
    "name": "r",
    "action": "read",
    "selector": "tr",
    "extract": {"n": {"type": "int"}},
}


def test_a_failed_field_reaches_the_flow_result(mock_session: MagicMock) -> None:
    mock_session.parse_elements.return_value = [{"n": None}]
    mock_session.extract_errors = [FAILED]

    result = run_flow(mock_session, load_flow_document({"steps": [READ]}), {})

    assert isinstance(result, FlowSuccess)
    assert result.extract_errors == [FAILED.model_copy(update={"step": "r"})]


def test_parse_logs_its_deprecation_once_per_run(
    mock_session: MagicMock, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    schema = tmp_path / "row.yaml"
    schema.write_text("name: Row\nfields:\n  n: {type: str | None, default: null}\n")
    mock_session.parse_elements.return_value = []
    parse = {"action": "parse", "selector": "tr", "schema_path": str(schema)}
    flow = load_flow_document(
        {"steps": [{"name": "a", **parse}, {"name": "b", **parse}]}
    )

    with caplog.at_level(logging.WARNING, logger="llm_browser.actions"):
        run_flow(mock_session, flow, {})
        run_flow(mock_session, flow, {})

    assert [r.getMessage() for r in caplog.records] == [PARSE_DEPRECATED] * 2


def test_a_secret_in_an_input_is_redacted(mock_session: MagicMock) -> None:
    mock_session.parse_elements.return_value = [{"n": None}]
    mock_session.extract_errors = [FAILED.model_copy(update={"input": "pw hunter2"})]

    result = run_flow(
        mock_session, load_flow_document({"steps": [READ]}), {}, redact=["hunter2"]
    )

    assert "hunter2" not in str(result.extract_errors[0].input)
