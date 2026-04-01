"""Tests for Pydantic model serialization round-trips."""

import pytest

from llm_browser.models import (
    EvalStep,
    Flow,
    FlowData,
    FlowResult,
    FlowState,
    GotoStep,
    SessionInfo,
    validate_step,
)


def test_session_info_round_trip() -> None:
    info = SessionInfo(
        pid=1234, cdp_url="ws://127.0.0.1:9222/devtools", user_data_dir="/tmp/ud"
    )
    json_str = info.model_dump_json()
    restored = SessionInfo.model_validate_json(json_str)
    assert restored == info


def test_flow_state_round_trip() -> None:
    state = FlowState(flow_path="/tmp/flow.yaml", data={"rfc": "XEXX"}, current_index=2)
    json_str = state.model_dump_json()
    restored = FlowState.model_validate_json(json_str)
    assert restored.flow_path == "/tmp/flow.yaml"
    assert restored.data == {"rfc": "XEXX"}
    assert restored.current_index == 2


def test_flow_state_defaults() -> None:
    state = FlowState(flow_path="/tmp/f.yaml", data={})
    assert state.current_index == 0


def test_flow_result_round_trip() -> None:
    result = FlowResult(step="check", data='{"cp": "05330"}', screenshot="/tmp/s.png")
    json_str = result.model_dump_json()
    restored = FlowResult.model_validate_json(json_str)
    assert restored.step == "check"
    assert restored.completed is False


def test_flow_result_defaults() -> None:
    result = FlowResult(step="end", completed=True)
    assert result.data is None
    assert result.screenshot is None


def test_flow_result_exclude_none() -> None:
    result = FlowResult(step="end", completed=True)
    d = result.model_dump(exclude_none=True)
    assert "data" not in d
    assert "screenshot" not in d
    assert d["step"] == "end"
    assert d["completed"] is True


def test_step_defaults() -> None:
    step = EvalStep(name="s1")
    assert step.fields == []
    assert step.when == []
    assert step.action is None
    assert step.checkpoint is False


def test_step_discriminated_union() -> None:
    step = validate_step({"name": "s1", "action": "goto", "url": "https://example.com"})
    assert isinstance(step, GotoStep)
    assert step.action == "goto"
    assert step.url == "https://example.com"


def test_flow_round_trip() -> None:
    flow = Flow(
        steps=[EvalStep(name="s1", eval="1+1"), EvalStep(name="s2", checkpoint=True)]
    )
    data = flow.model_dump()
    restored = Flow.model_validate(data)
    assert len(restored.steps) == 2
    assert restored.steps[0].name == "s1"
    assert restored.steps[1].checkpoint is True


def test_flow_data_to_template_dict() -> None:
    data = FlowData.model_validate({"rfc": "XEXX", "cp": None})
    d = data.to_template_dict()
    assert d == {"rfc": "XEXX"}


def test_flow_validate_data_registered_param() -> None:
    flow = Flow(params=["rfc"], steps=[EvalStep(name="s1")])
    data = flow.validate_data({"rfc": "XEXX"})
    assert data.rfc == "XEXX"  # type: ignore[attr-defined]


def test_flow_validate_data_missing_required() -> None:
    flow = Flow(params=["rfc"], steps=[EvalStep(name="s1")])
    with pytest.raises(ValueError, match="Missing required param: rfc"):
        flow.validate_data({})


def test_flow_validate_data_registered_optional() -> None:
    flow = Flow(params=["cp"], steps=[EvalStep(name="s1")])
    data = flow.validate_data({})
    assert data.cp is None  # type: ignore[attr-defined]


def test_flow_validate_data_inline_param() -> None:
    flow = Flow(
        params=[{"custom": {"required": False, "default": "00000"}}],
        steps=[EvalStep(name="s1")],
    )
    data = flow.validate_data({})
    assert data.custom == "00000"  # type: ignore[attr-defined]


def test_flow_validate_data_mixed_params() -> None:
    flow = Flow(
        params=["rfc", {"region": {"required": False, "default": "MX"}}],
        steps=[EvalStep(name="s1")],
    )
    data = flow.validate_data({"rfc": "XEXX"})
    assert data.rfc == "XEXX"  # type: ignore[attr-defined]
    assert data.region == "MX"  # type: ignore[attr-defined]


def test_flow_validate_data_extra_keys_passed_through() -> None:
    flow = Flow(params=["rfc"], steps=[EvalStep(name="s1")])
    data = flow.validate_data({"rfc": "XEXX", "extra": "value"})
    assert data.extra == "value"  # type: ignore[attr-defined]


def test_flow_validate_data_unregistered_param_treated_as_required() -> None:
    flow = Flow(params=["nonexistent"], steps=[EvalStep(name="s1")])
    with pytest.raises(ValueError, match="Missing required param"):
        flow.validate_data({})
