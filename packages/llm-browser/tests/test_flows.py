"""Tests for flow loading, step execution, and the `run_flow_file` entry."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml
from pydantic import ValidationError

from llm_browser.actions import SkippedResult
from llm_browser.flow_files import load_flow, run_flow_file
from llm_browser.flows import run_flow
from llm_browser.models import (
    ClickStep,
    EvalStep,
    Flow,
    FlowData,
    FlowError,
    FlowSuccess,
    PageProbe,
)
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


# --- load_flow ---


def test_load_flow(tmp_path: Path) -> None:
    path = _write_flow(tmp_path, [{"name": "step1"}, {"name": "step2"}])
    flow = load_flow(path)
    assert len(flow.steps) == 2
    assert flow.steps[0].name == "step1"


def test_load_flow_rejects_bad_yaml(tmp_path: Path) -> None:
    path = tmp_path / "flow.yaml"
    path.write_text("steps: [\n  - name: x\n")
    with pytest.raises(ValueError, match="invalid flow yaml"):
        load_flow(path)


# --- should_skip ---


def test_should_skip_no_when(mock_session: MagicMock) -> None:
    assert should_skip(mock_session, EvalStep(name="s"), _flow_data()) is False


def test_should_skip_truthy_passes(mock_session: MagicMock) -> None:
    step = EvalStep(name="s", when=[{"field": "enabled", "op": "is_truthy"}])
    assert should_skip(mock_session, step, _flow_data(enabled=True)) is False


def test_should_skip_truthy_fails(mock_session: MagicMock) -> None:
    step = EvalStep(name="s", when=[{"field": "enabled", "op": "is_truthy"}])
    assert should_skip(mock_session, step, _flow_data(enabled=False)) is True


def test_should_skip_eq(mock_session: MagicMock) -> None:
    step = EvalStep(name="s", when=[{"field": "mode", "op": "eq", "value": "fast"}])
    assert should_skip(mock_session, step, _flow_data(mode="fast")) is False
    assert should_skip(mock_session, step, _flow_data(mode="slow")) is True


def test_should_skip_not_null(mock_session: MagicMock) -> None:
    step = EvalStep(name="s", when=[{"field": "cp", "op": "not_null"}])
    assert should_skip(mock_session, step, _flow_data(cp="05330")) is False
    assert should_skip(mock_session, step, _flow_data(cp=None)) is True
    assert should_skip(mock_session, step, _flow_data()) is True


def test_should_skip_multiple_conditions(mock_session: MagicMock) -> None:
    step = EvalStep(
        name="s",
        when=[
            {"field": "enabled", "op": "is_truthy"},
            {"field": "mode", "op": "eq", "value": "fast"},
        ],
    )
    assert (
        should_skip(mock_session, step, _flow_data(enabled=True, mode="fast")) is False
    )
    assert (
        should_skip(mock_session, step, _flow_data(enabled=True, mode="slow")) is True
    )


def test_should_skip_element_exists(mock_session: MagicMock) -> None:
    step = EvalStep(
        name="s",
        when=[{"element_exists": {"selector": "#btn"}}],
    )
    mock_session.element_exists.return_value = True
    assert should_skip(mock_session, step, _flow_data()) is False
    mock_session.element_exists.return_value = False
    assert should_skip(mock_session, step, _flow_data()) is True


# --- execute_step ---


def test_execute_step_skipped_by_when(mock_session: MagicMock) -> None:
    step = EvalStep(
        name="optional",
        when=[{"field": "needed", "op": "is_truthy"}],
        eval="something()",
    )
    result = execute_step(mock_session, step, _flow_data(needed=False))
    assert isinstance(result, SkippedResult)
    mock_session.driver.evaluate.assert_not_called()


def test_execute_step_template_substitution(mock_session: MagicMock) -> None:
    mock_session.driver.evaluate.return_value = "ok"

    step = EvalStep(name="t", eval="document.getElementById('{{ fid }}').value")
    execute_step(mock_session, step, _flow_data(fid="myfield"))
    mock_session.driver.evaluate.assert_called_once_with(
        mock_session.get_page.return_value,
        "document.getElementById('myfield').value",
    )


# --- run_flow_file ---


def test_run_completes_to_end(tmp_path: Path, mock_session: MagicMock) -> None:
    steps = [{"name": "s1", "action": "click", "selector": "#btn"}]
    path = _write_flow(tmp_path, steps)
    result = run_flow_file(mock_session, path, {})
    assert isinstance(result, FlowSuccess)


def test_run_from_step_skips_prior_steps(
    tmp_path: Path,
    mock_session: MagicMock,
) -> None:
    """`from_step="step3"` skips step1 and step2; only step3 runs."""
    steps = [
        {"name": "step1", "action": "click", "selector": "#a"},
        {"name": "step2", "action": "click", "selector": "#b"},
        {"name": "step3", "action": "click", "selector": "#c"},
    ]
    path = _write_flow(tmp_path, steps)
    result = run_flow_file(mock_session, path, {}, from_step="step3")
    assert isinstance(result, FlowSuccess)
    # Only step3's selector hit the driver — step1 and step2 were skipped.
    assert mock_session.find.call_count == 1
    selector = mock_session.find.call_args.args[0]
    assert "c" in str(selector)


def test_run_from_step_unknown_raises(tmp_path: Path, mock_session: MagicMock) -> None:
    steps = [{"name": "only", "action": "click", "selector": "#a"}]
    path = _write_flow(tmp_path, steps)
    with pytest.raises(ValueError, match="step 'missing' not found in flow"):
        run_flow_file(mock_session, path, {}, from_step="missing")


def test_run_emits_retry_hint_on_failure(
    tmp_path: Path,
    mock_session: MagicMock,
) -> None:
    """When a step fails, run_flow attaches a RetryHint to the FlowError."""
    steps = [
        {"name": "ok", "action": "click", "selector": "#a"},
        {"name": "boom", "action": "click", "selector": "#missing"},
    ]
    path = _write_flow(tmp_path, steps)

    # First click succeeds; second click raises so the action fails.
    locator = MagicMock()
    locator.count.return_value = 1
    mock_session.find.side_effect = [locator, TimeoutError("element missing")]

    result = run_flow_file(mock_session, path, {"k": "v"})
    assert isinstance(result, FlowError)
    assert result.step == "boom"
    assert result.retry_hint is not None
    assert result.retry_hint.failed_step == "boom"
    assert result.retry_hint.flow_path == str(path)
    assert result.retry_hint.data == {"k": "v"}


def test_run_emits_retry_hint_pointing_to_parent_for_subflow_failure(
    tmp_path: Path,
    mock_session: MagicMock,
) -> None:
    """When a step inside a sub-flow fails, the hint's `failed_step`
    is the parent's run-flow step name (not the inner step) so
    `--from <hint.failed_step>` resolves against the parent flow."""
    mock_session.find.side_effect = TimeoutError("element missing")
    _write_named_flow(
        tmp_path,
        "child.yaml",
        [{"name": "inner-click", "action": "click", "selector": "#missing"}],
    )
    parent = _write_named_flow(
        tmp_path,
        "parent.yaml",
        [{"name": "do-thing", "action": "run-flow", "flow": "child.yaml"}],
    )
    result = run_flow_file(mock_session, parent, {})
    assert isinstance(result, FlowError)
    assert result.retry_hint is not None
    # Hint uses the parent's run-flow step name, not the qualified path.
    assert result.retry_hint.failed_step == "do-thing"
    # The result itself carries the qualified path so diagnostics
    # can show where in the tree the failure happened.
    assert result.step == "do-thing/inner-click"


def test_run_validates_params(tmp_path: Path, mock_session: MagicMock) -> None:
    steps = [{"name": "s1", "eval": "fillRfc('{{ rfc }}')"}]
    path = _write_flow(tmp_path, steps, params=["rfc"])

    with pytest.raises(ValueError, match="Missing required param: rfc"):
        run_flow_file(mock_session, path, {})


def test_run_with_registered_and_inline_params(
    tmp_path: Path,
    mock_session: MagicMock,
) -> None:
    mock_session.driver.evaluate.return_value = "ok"

    params: list[str | dict[str, Any]] = [
        "rfc",
        {"region": {"required": False, "default": "MX"}},
    ]
    steps = [{"name": "s1", "eval": "fill('{{ rfc }}', '{{ region }}')"}]
    path = _write_flow(tmp_path, steps, params=params)
    result = run_flow_file(mock_session, path, {"rfc": "XEXX"})

    assert isinstance(result, FlowSuccess)
    mock_session.driver.evaluate.assert_called_once_with(
        mock_session.get_page.return_value, "fill('XEXX', 'MX')"
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


def test_run_flow_dispatches_subflow(tmp_path: Path, mock_session: MagicMock) -> None:
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
    result = run_flow_file(mock_session, parent, {})

    assert isinstance(result, FlowSuccess)
    # Both child clicks fired against the mock_session.
    assert mock_session.find.call_count == 2


def test_run_flow_param_passthrough(tmp_path: Path, mock_session: MagicMock) -> None:
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
    run_flow_file(mock_session, parent, {"target": "submit"})
    # mock_session.find was called with a parsed selector for #submit
    args, _ = mock_session.find.call_args
    assert "submit" in str(args[0])


def test_run_flow_optional_swallows_child_failure(
    tmp_path: Path,
    mock_session: MagicMock,
) -> None:
    # Force the click action to raise so the child's first step fails.
    mock_session.driver.click.side_effect = TimeoutError("button missing")
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
    mock_session.driver.click.side_effect = [TimeoutError("button missing"), None]
    result = run_flow_file(mock_session, parent, {})
    assert isinstance(result, FlowSuccess)


def test_run_flow_required_failure_bubbles(
    tmp_path: Path,
    mock_session: MagicMock,
) -> None:
    mock_session.driver.click.side_effect = TimeoutError("button missing")
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
    result = run_flow_file(mock_session, parent, {})
    # Child failure surfaces to the parent runner; not completed.
    assert isinstance(result, FlowError)


def test_run_flow_rejects_nested_subflow(
    tmp_path: Path,
    mock_session: MagicMock,
) -> None:
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
    with pytest.raises(ValidationError, match="nested sub-flows are not allowed"):
        run_flow_file(mock_session, parent, {})


def test_run_flow_resolves_relative_to_parent_dir(
    tmp_path: Path,
    mock_session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
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

    result = run_flow_file(mock_session, parent, {})
    assert isinstance(result, FlowSuccess)
    assert mock_session.find.call_count == 1


def test_load_flow_validates_subflows_eagerly(tmp_path: Path) -> None:
    """`load_flow` resolves every `run-flow` reference at load time,
    so a child that itself contains a `run-flow` step is rejected
    before the browser ever launches."""
    _write_named_flow(
        tmp_path,
        "grandchild.yaml",
        [{"name": "g1", "action": "click", "selector": "#x"}],
    )
    _write_named_flow(
        tmp_path,
        "bad.yaml",
        [{"name": "nested", "action": "run-flow", "flow": "grandchild.yaml"}],
    )
    parent = _write_named_flow(
        tmp_path,
        "parent.yaml",
        [{"name": "include", "action": "run-flow", "flow": "bad.yaml"}],
    )
    with pytest.raises(ValidationError, match="nested sub-flows are not allowed"):
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


def test_load_flow_resolves_refs_with_selector_map(tmp_path: Path) -> None:
    """`load_flow(path, selector_map=...)` expands `ref:` into
    concrete `selector:` via pydantic's before-validator."""
    flow_file = _write_named_flow(
        tmp_path,
        "f.yaml",
        [{"name": "click-x", "action": "click", "ref": "ui.button"}],
    )
    selector_map = {"ui.button": {"id": "the-button"}}
    flow = load_flow(flow_file, selector_map=selector_map)
    step = flow.steps[0]
    # Selector survived validation as the resolved spec.
    assert step.selector.id == "the-button"  # type: ignore[union-attr]


def test_load_flow_unknown_ref_fails(tmp_path: Path) -> None:
    """Unknown ref raises ValidationError — caught at load time, not
    deferred into a 'selector required' cascade."""
    flow_file = _write_named_flow(
        tmp_path,
        "f.yaml",
        [{"name": "click-x", "action": "click", "ref": "ui.missing"}],
    )
    with pytest.raises(ValidationError, match="not found in selector_map"):
        load_flow(flow_file, selector_map={"ui.button": {"id": "x"}})


def test_load_flow_resolves_refs_in_subflow(tmp_path: Path) -> None:
    """Selector map reaches sub-flow children via the validation
    context that RunFlowStep's after-validator threads through."""
    from llm_browser.models import RunFlowStep

    _write_named_flow(
        tmp_path,
        "child.yaml",
        [{"name": "click-y", "action": "click", "ref": "ui.button"}],
    )
    parent = _write_named_flow(
        tmp_path,
        "parent.yaml",
        [{"name": "include", "action": "run-flow", "flow": "child.yaml"}],
    )
    flow = load_flow(parent, selector_map={"ui.button": {"id": "the-button"}})
    runflow = flow.steps[0]
    assert isinstance(runflow, RunFlowStep)
    assert runflow.subflow is not None
    child_step = runflow.subflow.steps[0]
    assert child_step.selector.id == "the-button"  # type: ignore[union-attr]


def test_run_flow_when_skips_subflow(tmp_path: Path, mock_session: MagicMock) -> None:
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
    result = run_flow_file(mock_session, parent, {})
    assert isinstance(result, FlowSuccess)
    assert mock_session.find.call_count == 0


# --- execute_step: human_needed ---


def _failing_click(session: MagicMock) -> ClickStep:
    session.find.side_effect = ValueError("Expected 1 element for '#go', found 0")
    return ClickStep(action="click", name="go", selector="#go")


def test_execute_step_flags_a_page_that_needs_a_human(mock_session: MagicMock) -> None:
    step = _failing_click(mock_session)
    mock_session.probe.return_value = PageProbe(password_visible=True, text="Sign in")
    error = execute_step(mock_session, step, _flow_data())
    assert isinstance(error, FlowError)
    assert error.human_needed is True


def test_execute_step_leaves_human_needed_false_on_an_ordinary_page(
    mock_session: MagicMock,
) -> None:
    step = _failing_click(mock_session)
    error = execute_step(mock_session, step, _flow_data())
    assert isinstance(error, FlowError)
    assert error.human_needed is False


def test_execute_step_keeps_the_original_error_when_the_probe_fails(
    mock_session: MagicMock,
) -> None:
    step = _failing_click(mock_session)
    mock_session.probe.side_effect = RuntimeError("CDP connection closed")
    error = execute_step(mock_session, step, _flow_data())
    assert isinstance(error, FlowError)
    assert error.human_needed is False
    assert "found 0" in str(error.data)
    mock_session.take_screenshot.assert_called_once()


def test_run_flow_carries_human_needed_through_to_the_caller(
    mock_session: MagicMock,
) -> None:
    step = _failing_click(mock_session)
    mock_session.probe.return_value = PageProbe(challenge=True)
    result = run_flow(mock_session, Flow(steps=[step]), {})
    assert isinstance(result, FlowError)
    assert result.human_needed is True
