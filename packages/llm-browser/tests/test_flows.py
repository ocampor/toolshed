"""Tests for flow loading, step execution, and FlowRunner."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from llm_browser.flows import FlowRunner, load_flow
from llm_browser.models import EvalStep, FlowData, FlowState
from llm_browser.session import BrowserSession
from llm_browser.steps import execute_step, should_skip


def _flow_data(**kwargs: object) -> FlowData:
    return FlowData.model_validate(kwargs)


def _write_flow(
    tmp_path: Path,
    steps: list[dict[str, Any]],
    params: list[str | dict[str, Any]] | None = None,
) -> Path:
    path = tmp_path / "flow.yaml"
    flow_dict: dict[str, Any] = {"steps": steps}
    if params:
        flow_dict["params"] = params
    path.write_text(yaml.dump(flow_dict))
    return path


def _mock_session(tmp_path: Path) -> MagicMock:
    session = MagicMock(spec=BrowserSession)
    session.session_dir = tmp_path
    page = MagicMock()
    session.get_page.return_value = page
    session.take_screenshot.return_value = tmp_path / "screenshot.png"
    session.element_exists.return_value = True
    locator = MagicMock()
    locator.count.return_value = 1
    session.find.return_value = locator
    session.find_all.return_value = locator
    return session


# --- load_flow ---


def test_load_flow(tmp_path: Path) -> None:
    path = _write_flow(tmp_path, [{"name": "step1"}, {"name": "step2"}])
    flow = load_flow(path)
    assert len(flow.steps) == 2
    assert flow.steps[0].name == "step1"


def test_load_flow_validates(tmp_path: Path) -> None:
    path = _write_flow(tmp_path, [{"name": "s1", "checkpoint": True}])
    flow = load_flow(path)
    assert flow.steps[0].checkpoint is True


# --- should_skip ---


def test_should_skip_no_when(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    assert should_skip(session, EvalStep(name="s"), _flow_data()) is False


def test_should_skip_truthy_passes(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    step = EvalStep(name="s", when=[{"field": "enabled", "op": "is_truthy"}])
    assert should_skip(session, step, _flow_data(enabled=True)) is False


def test_should_skip_truthy_fails(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    step = EvalStep(name="s", when=[{"field": "enabled", "op": "is_truthy"}])
    assert should_skip(session, step, _flow_data(enabled=False)) is True


def test_should_skip_eq(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    step = EvalStep(name="s", when=[{"field": "mode", "op": "eq", "value": "fast"}])
    assert should_skip(session, step, _flow_data(mode="fast")) is False
    assert should_skip(session, step, _flow_data(mode="slow")) is True


def test_should_skip_not_null(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    step = EvalStep(name="s", when=[{"field": "cp", "op": "not_null"}])
    assert should_skip(session, step, _flow_data(cp="05330")) is False
    assert should_skip(session, step, _flow_data(cp=None)) is True
    assert should_skip(session, step, _flow_data()) is True


def test_should_skip_multiple_conditions(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    step = EvalStep(
        name="s",
        when=[
            {"field": "enabled", "op": "is_truthy"},
            {"field": "mode", "op": "eq", "value": "fast"},
        ],
    )
    assert should_skip(session, step, _flow_data(enabled=True, mode="fast")) is False
    assert should_skip(session, step, _flow_data(enabled=True, mode="slow")) is True


def test_should_skip_element_exists(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    step = EvalStep(
        name="s",
        when=[{"element_exists": {"selector": "#btn"}}],
    )
    session.element_exists.return_value = True
    assert should_skip(session, step, _flow_data()) is False
    session.element_exists.return_value = False
    assert should_skip(session, step, _flow_data()) is True


# --- execute_step ---


def test_execute_step_with_eval_checkpoint(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    session.get_page.return_value.evaluate.return_value = '{"cp": "05330"}'

    step = EvalStep(name="check", eval="someJs()", checkpoint=True)
    result = execute_step(session, step, _flow_data())

    assert result is not None
    assert result.step == "check"
    assert result.data == '{"cp": "05330"}'


def test_execute_step_skipped_by_when(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    step = EvalStep(
        name="optional",
        when=[{"field": "needed", "op": "is_truthy"}],
        eval="something()",
    )
    result = execute_step(session, step, _flow_data(needed=False))
    assert result is None
    session.get_page.return_value.evaluate.assert_not_called()


def test_execute_step_template_substitution(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    page = session.get_page.return_value
    page.evaluate.return_value = "ok"

    step = EvalStep(name="t", eval="document.getElementById('{{ fid }}').value")
    execute_step(session, step, _flow_data(fid="myfield"))
    page.evaluate.assert_called_once_with("document.getElementById('myfield').value")


# --- FlowRunner ---


def test_run_pauses_at_checkpoint(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    session.get_page.return_value.evaluate.return_value = "result1"

    steps: list[dict[str, Any]] = [
        {"name": "s1", "eval": "1+1"},
        {"name": "s2", "eval": "getVal()", "checkpoint": True},
        {"name": "s3", "eval": "should_not_run()"},
    ]
    path = _write_flow(tmp_path, steps)
    runner = FlowRunner(session)
    result = runner.run(path, {})

    assert result.step == "s2"
    assert result.completed is False


def test_run_completes_without_checkpoint(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    steps = [{"name": "s1", "action": "click", "selector": "#btn"}]
    path = _write_flow(tmp_path, steps)
    runner = FlowRunner(session)
    result = runner.run(path, {})
    assert result.completed is True


def test_run_saves_state_at_checkpoint(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    session.get_page.return_value.evaluate.return_value = "v"

    steps = [{"name": "s1", "eval": "x()", "checkpoint": True}]
    path = _write_flow(tmp_path, steps)
    runner = FlowRunner(session)
    runner.run(path, {"key": "val"})

    state_file = tmp_path / "flow_state.json"
    assert state_file.exists()
    state = FlowState.model_validate_json(state_file.read_text())
    assert state.current_index == 1
    assert state.data == {"key": "val"}


def test_resume_continues_from_checkpoint(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)

    steps: list[dict[str, Any]] = [
        {"name": "s1", "eval": "first()", "checkpoint": True},
        {"name": "s2", "action": "click", "selector": "#done"},
    ]
    path = _write_flow(tmp_path, steps)
    runner = FlowRunner(session)

    state = FlowState(flow_path=str(path), data={}, current_index=1)
    (tmp_path / "flow_state.json").write_text(state.model_dump_json())

    result = runner.resume()
    assert result.completed is True
    assert result.step == "s2"
    session.find.assert_called()


def test_resume_no_state_raises(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    runner = FlowRunner(session)
    with pytest.raises(RuntimeError, match="No flow to resume"):
        runner.resume()


def test_resume_merges_data(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)

    steps: list[dict[str, Any]] = [
        {"name": "s1", "eval": "first()", "checkpoint": True},
        {"name": "s2", "eval": "second()"},
    ]
    path = _write_flow(tmp_path, steps)
    runner = FlowRunner(session)

    state = FlowState(flow_path=str(path), data={"a": "1"}, current_index=1)
    (tmp_path / "flow_state.json").write_text(state.model_dump_json())

    runner.resume(data={"b": "2"})
    assert not (tmp_path / "flow_state.json").exists()


def test_run_validates_params(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    steps = [{"name": "s1", "eval": "fillRfc('{{ rfc }}')"}]
    path = _write_flow(tmp_path, steps, params=["rfc"])
    runner = FlowRunner(session)

    with pytest.raises(ValueError, match="Missing required param: rfc"):
        runner.run(path, {})


def test_run_with_registered_and_inline_params(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    session.get_page.return_value.evaluate.return_value = "ok"

    params: list[str | dict[str, Any]] = [
        "rfc",
        {"region": {"required": False, "default": "MX"}},
    ]
    steps = [{"name": "s1", "eval": "fill('{{ rfc }}', '{{ region }}')"}]
    path = _write_flow(tmp_path, steps, params=params)
    runner = FlowRunner(session)
    result = runner.run(path, {"rfc": "XEXX"})

    assert result.completed is True
    page = session.get_page.return_value
    page.evaluate.assert_called_once_with("fill('XEXX', 'MX')")
