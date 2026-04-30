"""Tests for flow loading, step execution, and FlowRunner."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml
from pydantic import ValidationError

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
    from llm_browser.behavior import Behavior

    session = MagicMock(spec=BrowserSession)
    session.session_dir = tmp_path
    session.behavior = Behavior.off()
    session._behavior_runtime = session.behavior.runtime()
    session.capture = "screenshot"
    session.driver = MagicMock()
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
    session.driver.evaluate.return_value = '{"cp": "05330"}'

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
    session.driver.evaluate.assert_not_called()


def test_execute_step_template_substitution(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    session.driver.evaluate.return_value = "ok"

    step = EvalStep(name="t", eval="document.getElementById('{{ fid }}').value")
    execute_step(session, step, _flow_data(fid="myfield"))
    session.driver.evaluate.assert_called_once_with(
        session.get_page.return_value,
        "document.getElementById('myfield').value",
    )


# --- FlowRunner ---


def test_run_pauses_at_checkpoint(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    session.driver.evaluate.return_value = "result1"

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
    session.driver.evaluate.return_value = "v"

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


def test_run_refuses_checkpoint_flow_when_session_cannot_resume(
    tmp_path: Path,
) -> None:
    """Flows with checkpoints require a driver+handle that survives Python exit."""
    session = _mock_session(tmp_path)
    from llm_browser.models import SessionInfo

    session._load_state.return_value = SessionInfo(
        driver="patchright", user_data_dir=str(tmp_path), mode="launched"
    )
    session._handle_from_state.side_effect = BrowserSession._handle_from_state.__get__(
        session
    )
    session.driver.can_resume_across_processes.return_value = False

    steps: list[dict[str, Any]] = [
        {"name": "s1", "eval": "noop()"},
        {"name": "pause", "checkpoint": True},
    ]
    path = _write_flow(tmp_path, steps)
    runner = FlowRunner(session)

    with pytest.raises(RuntimeError, match="cannot be resumed across"):
        runner.run(path, {})


def test_run_allows_checkpoint_flow_when_session_can_resume(tmp_path: Path) -> None:
    """Attach-mode patchright opts in to checkpoint flows via the driver hook."""
    session = _mock_session(tmp_path)
    from llm_browser.models import SessionInfo

    session._load_state.return_value = SessionInfo(
        driver="patchright",
        cdp_url="http://localhost:9222",
        user_data_dir="",
        mode="attached",
    )
    session._handle_from_state.side_effect = BrowserSession._handle_from_state.__get__(
        session
    )
    session.driver.can_resume_across_processes.return_value = True

    steps: list[dict[str, Any]] = [
        {"name": "s1", "eval": "noop()"},
        {"name": "pause", "checkpoint": True},
    ]
    path = _write_flow(tmp_path, steps)
    session.driver.evaluate.return_value = None
    runner = FlowRunner(session)
    result = runner.run(path, {})
    assert result.step == "pause"


def test_run_with_registered_and_inline_params(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    session.driver.evaluate.return_value = "ok"

    params: list[str | dict[str, Any]] = [
        "rfc",
        {"region": {"required": False, "default": "MX"}},
    ]
    steps = [{"name": "s1", "eval": "fill('{{ rfc }}', '{{ region }}')"}]
    path = _write_flow(tmp_path, steps, params=params)
    runner = FlowRunner(session)
    result = runner.run(path, {"rfc": "XEXX"})

    assert result.completed is True
    session.driver.evaluate.assert_called_once_with(
        session.get_page.return_value, "fill('XEXX', 'MX')"
    )


# --- run-flow (sub-flow composition) ---


def _write_named_flow(
    tmp_path: Path,
    name: str,
    steps: list[dict[str, Any]],
    params: list[str | dict[str, Any]] | None = None,
) -> Path:
    """Write a flow under a specific filename so sub-flow includes can reference it."""
    flow_dict: dict[str, Any] = {"steps": steps}
    if params:
        flow_dict["params"] = params
    path = tmp_path / name
    path.write_text(yaml.dump(flow_dict))
    return path


def test_run_flow_dispatches_subflow(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    _write_named_flow(
        tmp_path,
        "child.yaml",
        [
            {"name": "c1", "action": "click", "selector": "#a"},
            {"name": "c2", "action": "click", "selector": "#b"},
        ],
    )
    parent = _write_named_flow(
        tmp_path,
        "parent.yaml",
        [{"name": "include", "action": "run-flow", "flow": "child.yaml"}],
    )
    runner = FlowRunner(session)
    result = runner.run(parent, {})

    assert result.completed is True
    # Both child clicks fired against the session.
    assert session.find.call_count == 2


def test_run_flow_param_passthrough(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    _write_named_flow(
        tmp_path,
        "child.yaml",
        [{"name": "c1", "action": "click", "selector": "#{{ target }}"}],
        params=["target"],
    )
    parent = _write_named_flow(
        tmp_path,
        "parent.yaml",
        [
            {
                "name": "include",
                "action": "run-flow",
                "flow": "child.yaml",
                "data": {"target": "{{ target }}"},
            }
        ],
        params=["target"],
    )
    runner = FlowRunner(session)
    runner.run(parent, {"target": "submit"})
    # session.find was called with a parsed selector for #submit
    args, _ = session.find.call_args
    assert "submit" in str(args[0])


def test_run_flow_optional_swallows_child_failure(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    # Force the click action to raise so the child's first step fails.
    session.driver.click.side_effect = TimeoutError("button missing")
    _write_named_flow(
        tmp_path,
        "child.yaml",
        [{"name": "c1", "action": "click", "selector": "#missing"}],
    )
    parent = _write_named_flow(
        tmp_path,
        "parent.yaml",
        [
            {
                "name": "best-effort",
                "action": "run-flow",
                "flow": "child.yaml",
                "optional": True,
            },
            {"name": "after", "action": "click", "selector": "#after"},
        ],
    )
    # The parent's own click must succeed even when the sub-flow swallows.
    session.driver.click.side_effect = [TimeoutError("button missing"), None]
    runner = FlowRunner(session)
    result = runner.run(parent, {})
    assert result.completed is True


def test_run_flow_required_failure_bubbles(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    session.driver.click.side_effect = TimeoutError("button missing")
    _write_named_flow(
        tmp_path,
        "child.yaml",
        [{"name": "c1", "action": "click", "selector": "#missing"}],
    )
    parent = _write_named_flow(
        tmp_path,
        "parent.yaml",
        [{"name": "required", "action": "run-flow", "flow": "child.yaml"}],
    )
    runner = FlowRunner(session)
    result = runner.run(parent, {})
    # Child failure surfaces to the parent runner; not completed.
    assert result.completed is False


def test_run_flow_rejects_nested_subflow(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    _write_named_flow(
        tmp_path,
        "grandchild.yaml",
        [{"name": "g1", "action": "click", "selector": "#g"}],
    )
    _write_named_flow(
        tmp_path,
        "child.yaml",
        [{"name": "nested", "action": "run-flow", "flow": "grandchild.yaml"}],
    )
    parent = _write_named_flow(
        tmp_path,
        "parent.yaml",
        [{"name": "include", "action": "run-flow", "flow": "child.yaml"}],
    )
    runner = FlowRunner(session)
    with pytest.raises(ValidationError, match="nested sub-flows are not allowed"):
        runner.run(parent, {})


def test_run_flow_rejects_checkpoint_in_child(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    _write_named_flow(
        tmp_path,
        "child.yaml",
        [{"name": "cp", "eval": "noop()", "checkpoint": True}],
    )
    parent = _write_named_flow(
        tmp_path,
        "parent.yaml",
        [{"name": "include", "action": "run-flow", "flow": "child.yaml"}],
    )
    runner = FlowRunner(session)
    with pytest.raises(
        ValidationError, match="checkpointed sub-flows are not supported"
    ):
        runner.run(parent, {})


def test_run_flow_rejects_checkpoint_on_runflow_step(tmp_path: Path) -> None:
    """A run-flow step itself cannot be checkpointed (the constraint is at
    model validation, not at runtime)."""
    from pydantic import ValidationError

    from llm_browser.models import RunFlowStep

    with pytest.raises(ValidationError, match="run-flow steps cannot use checkpoint"):
        RunFlowStep(action="run-flow", flow="child.yaml", checkpoint=True)


def test_run_flow_resolves_relative_to_parent_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sub-flow paths resolve relative to the parent flow's directory,
    not CWD."""
    nested = tmp_path / "nested"
    nested.mkdir()
    _write_named_flow(
        nested,
        "child.yaml",
        [{"name": "c1", "action": "click", "selector": "#x"}],
    )
    parent = _write_named_flow(
        nested,
        "parent.yaml",
        [{"name": "include", "action": "run-flow", "flow": "child.yaml"}],
    )

    # Run from a *different* CWD to prove parent-relative resolution.
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.chdir(other)

    session = _mock_session(tmp_path)
    runner = FlowRunner(session)
    result = runner.run(parent, {})
    assert result.completed is True
    assert session.find.call_count == 1


def test_load_flow_validates_subflows_eagerly(tmp_path: Path) -> None:
    """`load_flow` resolves every `run-flow` reference at load time,
    so malformed children fail before the browser ever launches."""
    _write_named_flow(
        tmp_path,
        "bad.yaml",
        [{"name": "cp", "eval": "noop()", "checkpoint": True}],
    )
    parent = _write_named_flow(
        tmp_path,
        "parent.yaml",
        [{"name": "include", "action": "run-flow", "flow": "bad.yaml"}],
    )
    with pytest.raises(
        ValidationError, match="checkpointed sub-flows are not supported"
    ):
        load_flow(parent)


def test_load_flow_attaches_subflow_to_runflow_step(tmp_path: Path) -> None:
    """After `load_flow`, every RunFlowStep has its child attached."""
    from llm_browser.models import RunFlowStep, SubFlow

    _write_named_flow(
        tmp_path,
        "child.yaml",
        [{"name": "c1", "action": "click", "selector": "#a"}],
    )
    parent = _write_named_flow(
        tmp_path,
        "parent.yaml",
        [{"name": "include", "action": "run-flow", "flow": "child.yaml"}],
    )
    flow = load_flow(parent)
    step = flow.steps[0]
    assert isinstance(step, RunFlowStep)
    assert isinstance(step.subflow, SubFlow)
    assert step.subflow.steps[0].name == "c1"


def test_load_flow_missing_subflow_file_fails_at_load(tmp_path: Path) -> None:
    """A typo in `flow:` surfaces at load time — no runtime surprise."""
    parent = _write_named_flow(
        tmp_path,
        "parent.yaml",
        [{"name": "oops", "action": "run-flow", "flow": "nonexistent.yaml"}],
    )
    with pytest.raises(FileNotFoundError):
        load_flow(parent)


def test_run_flow_when_skips_subflow(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    _write_named_flow(
        tmp_path,
        "child.yaml",
        [{"name": "c1", "action": "click", "selector": "#a"}],
    )
    parent = _write_named_flow(
        tmp_path,
        "parent.yaml",
        [
            {
                "name": "maybe",
                "action": "run-flow",
                "flow": "child.yaml",
                "when": [{"field": "enabled", "op": "is_truthy"}],
            }
        ],
        params=[{"enabled": {"required": False, "default": False}}],
    )
    runner = FlowRunner(session)
    result = runner.run(parent, {})
    assert result.completed is True
    assert session.find.call_count == 0
