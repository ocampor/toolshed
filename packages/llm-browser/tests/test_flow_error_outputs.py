"""Tests for the partial outputs a `FlowError` carries back."""

from typing import Any
from unittest.mock import MagicMock

import yaml

from llm_browser.flows import load_flow_text, run_flow
from llm_browser.models import FlowError, FlowSuccess

DOM_STEP = {"name": "snap", "action": "dom", "selector": "#main"}
FAILING_STEP = {"name": "boom", "action": "click", "selector": "#a"}


def _flow_yaml(steps: list[dict[str, Any]]) -> str:
    return yaml.dump({"steps": steps})


def _run_flow_step(child_steps: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {
        "name": "child",
        "action": "run-flow",
        "flow": {"steps": child_steps},
        **extra,
    }


def _failing_run(session: MagicMock, flow_text: str) -> FlowError:
    session.find.side_effect = TimeoutError("element missing")
    result = run_flow(session, load_flow_text(flow_text), {})
    assert isinstance(result, FlowError)
    return result


def test_outputs_before_the_failure_are_returned(mock_session: MagicMock) -> None:
    result = _failing_run(mock_session, _flow_yaml([DOM_STEP, FAILING_STEP]))
    assert result.step == "boom"
    assert result.outputs == {"snap": "<p>hello</p>"}


def test_partial_outputs_are_redacted(mock_session: MagicMock) -> None:
    mock_session.dom.return_value = "<input value='s3cret'>"
    mock_session.find.side_effect = TimeoutError("element missing")
    flow = load_flow_text(_flow_yaml([DOM_STEP, FAILING_STEP]))
    result = run_flow(mock_session, flow, {}, redact=["s3cret"])
    assert isinstance(result, FlowError)
    assert result.outputs == {"snap": "<input value='***'>"}


def test_parent_outputs_survive_a_failing_subflow(mock_session: MagicMock) -> None:
    child_steps = [{**DOM_STEP, "name": "inner_snap"}, FAILING_STEP]
    parent = _flow_yaml([DOM_STEP, _run_flow_step(child_steps)])
    result = _failing_run(mock_session, parent)
    assert result.step == "child/boom"
    assert result.outputs == {
        "snap": "<p>hello</p>",
        "child/inner_snap": "<p>hello</p>",
    }


def test_optional_subflow_outputs_survive_its_own_failure(
    mock_session: MagicMock,
) -> None:
    child_steps = [{**DOM_STEP, "name": "inner_snap"}, FAILING_STEP]
    parent = _flow_yaml([_run_flow_step(child_steps, optional=True)])
    mock_session.find.side_effect = TimeoutError("element missing")
    result = run_flow(mock_session, load_flow_text(parent), {})
    assert isinstance(result, FlowSuccess)
    assert result.outputs == {"child/inner_snap": "<p>hello</p>"}


def test_no_outputs_when_the_first_step_fails(mock_session: MagicMock) -> None:
    assert _failing_run(mock_session, _flow_yaml([FAILING_STEP])).outputs == {}
