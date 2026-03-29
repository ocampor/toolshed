"""Tests for flow loading, step execution, and FlowRunner."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from llm_browser.flows import FlowRunner, load_flow
from llm_browser.steps import (
    apply_wait,
    dispatch_action,
    dispatch_eval,
    dispatch_fields,
    execute_step,
    maybe_checkpoint,
    should_skip,
)
from llm_browser.models import FlowData, FlowResult, FlowState, Step
from llm_browser.session import BrowserSession


def _write_flow(
    tmp_path: Path, steps: list[dict], params: dict | None = None
) -> Path:
    path = tmp_path / "flow.yaml"
    flow_dict: dict = {"steps": steps}
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
    return session


def test_load_flow(tmp_path: Path) -> None:
    path = _write_flow(tmp_path, [{"name": "step1"}, {"name": "step2"}])
    flow = load_flow(path)
    assert len(flow.steps) == 2
    assert flow.steps[0].name == "step1"


def test_load_flow_validates(tmp_path: Path) -> None:
    path = _write_flow(tmp_path, [{"name": "s1", "checkpoint": True}])
    flow = load_flow(path)
    assert flow.steps[0].checkpoint is True
    assert flow.steps[0].fields == []


def testshould_skip_no_when() -> None:
    assert should_skip(Step(name="s"), FlowData()) is False


def testshould_skip_truthy_passes() -> None:
    step = Step(name="s", when=[{"field": "enabled", "op": "is_truthy"}])
    assert should_skip(step, FlowData(enabled=True)) is False


def testshould_skip_truthy_fails() -> None:
    step = Step(name="s", when=[{"field": "enabled", "op": "is_truthy"}])
    assert should_skip(step, FlowData(enabled=False)) is True


def testshould_skip_eq() -> None:
    step = Step(name="s", when=[{"field": "mode", "op": "eq", "value": "fast"}])
    assert should_skip(step, FlowData(mode="fast")) is False
    assert should_skip(step, FlowData(mode="slow")) is True


def testshould_skip_not_null() -> None:
    step = Step(name="s", when=[{"field": "cp", "op": "not_null"}])
    assert should_skip(step, FlowData(cp="05330")) is False
    assert should_skip(step, FlowData(cp=None)) is True
    assert should_skip(step, FlowData()) is True


def testshould_skip_multiple_conditions() -> None:
    step = Step(
        name="s",
        when=[
            {"field": "enabled", "op": "is_truthy"},
            {"field": "mode", "op": "eq", "value": "fast"},
        ],
    )
    assert should_skip(step, FlowData(enabled=True, mode="fast")) is False
    assert should_skip(step, FlowData(enabled=True, mode="slow")) is True


def testdispatch_action_click() -> None:
    page = MagicMock()
    dispatch_action(page, Step(name="s", action="click", selector="#btn"))
    page.click.assert_called_once_with("#btn")


def testdispatch_action_dismiss_modal() -> None:
    page = MagicMock()
    btn = MagicMock()
    page.query_selector.side_effect = [MagicMock(), btn]
    dispatch_action(page, Step(name="s", action="dismiss_modal"))
    btn.click.assert_called_once()


def testdispatch_action_none() -> None:
    page = MagicMock()
    dispatch_action(page, Step(name="no_action"))
    page.click.assert_not_called()


def testdispatch_eval_runs_js() -> None:
    page = MagicMock()
    page.evaluate.return_value = "result"
    result = dispatch_eval(page, Step(name="s", eval="1+1"))
    assert result == "result"
    page.evaluate.assert_called_once_with("1+1")


def testdispatch_eval_no_eval() -> None:
    page = MagicMock()
    assert dispatch_eval(page, Step(name="no_eval")) is None


def testmaybe_checkpoint_returns_result(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    result = maybe_checkpoint(
        session, Step(name="check", checkpoint=True), "eval_data"
    )
    assert result is not None
    assert result.step == "check"
    assert result.data == "eval_data"
    session.take_screenshot.assert_called_once()


def testmaybe_checkpoint_no_checkpoint(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    assert maybe_checkpoint(session, Step(name="s"), None) is None


def test_execute_step_with_eval_checkpoint(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    session.get_page.return_value.evaluate.return_value = '{"cp": "05330"}'

    step = Step(name="check", eval="someJs()", checkpoint=True)
    result = execute_step(session, step, FlowData())

    assert result is not None
    assert result.step == "check"
    assert result.data == '{"cp": "05330"}'


def test_execute_step_skipped_by_when(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    step = Step(
        name="optional",
        when=[{"field": "needed", "op": "is_truthy"}],
        eval="something()",
    )
    result = execute_step(session, step, FlowData(needed=False))
    assert result is None
    session.get_page.assert_not_called()


def test_execute_step_template_substitution(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    page = session.get_page.return_value
    page.evaluate.return_value = "ok"

    step = Step(name="t", eval="document.getElementById('{{ fid }}').value")
    execute_step(session, step, FlowData(fid="myfield"))
    page.evaluate.assert_called_once_with("document.getElementById('myfield').value")


def test_run_pauses_at_checkpoint(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    session.get_page.return_value.evaluate.return_value = "result1"

    steps = [
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
    page = session.get_page.return_value

    steps = [
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
    page.click.assert_called_once_with("#done")


def test_resume_no_state_raises(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    runner = FlowRunner(session)
    with pytest.raises(RuntimeError, match="No flow to resume"):
        runner.resume()


def test_resume_merges_data(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)

    steps = [
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

    params = ["rfc", {"region": {"required": False, "default": "MX"}}]
    steps = [{"name": "s1", "eval": "fill('{{ rfc }}', '{{ region }}')"}]
    path = _write_flow(tmp_path, steps, params=params)
    runner = FlowRunner(session)
    result = runner.run(path, {"rfc": "XEXX"})

    assert result.completed is True
    page = session.get_page.return_value
    page.evaluate.assert_called_once_with("fill('XEXX', 'MX')")
