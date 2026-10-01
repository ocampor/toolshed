"""Typed-read warnings and the parse deprecation reach the flow result."""

from pathlib import Path
from unittest.mock import MagicMock

from llm_browser.constants import PARSE_DEPRECATED
from llm_browser.flows import load_flow_document, run_flow
from llm_browser.models import FlowSuccess
from llm_browser.results import ExtractWarning

FAILED = ExtractWarning(field="n", raw="x", reason="could not convert 'x' to int")


def test_a_failed_conversion_reaches_the_flow_result(mock_session: MagicMock) -> None:
    mock_session.parse_elements.return_value = [{"n": None}]
    mock_session.extract_warnings = [FAILED]
    read = {"action": "read", "selector": "tr", "extract": {"n": {"type": "int"}}}
    flow = load_flow_document({"steps": [{"name": "r", **read}]})

    result = run_flow(mock_session, flow, {})

    assert isinstance(result, FlowSuccess)
    assert result.extract_warnings == [FAILED.model_copy(update={"step": "r"})]


def test_parse_warns_once_per_run(mock_session: MagicMock, tmp_path: Path) -> None:
    schema = tmp_path / "row.yaml"
    schema.write_text("name: Row\nfields:\n  n: {type: str | None, default: null}\n")
    mock_session.parse_elements.return_value = []
    parse = {"action": "parse", "selector": "tr", "schema_path": str(schema)}
    steps = [{"name": "a", **parse}, {"name": "b", **parse}]

    result = run_flow(mock_session, load_flow_document({"steps": steps}), {})

    assert isinstance(result, FlowSuccess)
    assert result.extract_warnings == [
        ExtractWarning(step="a", field="parse", raw="", reason=PARSE_DEPRECATED)
    ]


def test_a_secret_in_a_raw_value_is_redacted(mock_session: MagicMock) -> None:
    mock_session.parse_elements.return_value = [{"n": None}]
    mock_session.extract_warnings = [FAILED.model_copy(update={"raw": "pw hunter2"})]
    read = {"action": "read", "selector": "tr", "extract": {"n": {"type": "int"}}}
    flow = load_flow_document({"steps": [{"name": "r", **read}]})

    result = run_flow(mock_session, flow, {}, redact=["hunter2"])

    assert "hunter2" not in result.extract_warnings[0].raw
