"""The `wait_for` flow step: model validation, failure capture, optional skip."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml
from click.testing import CliRunner
from pydantic import ValidationError

from llm_browser.actions import SkippedResult, VoidResult, execute_action
from llm_browser.cli import main
from llm_browser.constants import (
    DEFAULT_POLL_INTERVAL_MS,
    DEFAULT_SETTLE_MS,
    DEFAULT_WAIT_TIMEOUT_MS,
)
from llm_browser.flows import load_flow_text, run_flow
from llm_browser.models import FlowError, FlowSuccess, WaitForStep, validate_step
from llm_browser.steps import execute_step

TIMEOUT_MESSAGE = "'#late' did not become visible within 3000ms"


def wait_for_step(**overrides: Any) -> dict[str, Any]:
    return {"name": "await_it", "action": "wait_for", "selector": "#late", **overrides}


# --- Step model ---


def test_defaults_come_from_constants() -> None:
    step = validate_step(wait_for_step())
    assert isinstance(step, WaitForStep)
    assert step.state == "attached"
    assert step.timeout == DEFAULT_WAIT_TIMEOUT_MS
    assert step.interval == DEFAULT_POLL_INTERVAL_MS
    assert step.settle == DEFAULT_SETTLE_MS


@pytest.mark.parametrize(
    "state", ["attached", "detached", "visible", "hidden", "stable"]
)
def test_every_wait_state_validates(state: str) -> None:
    assert validate_step(wait_for_step(state=state)).state == state


@pytest.mark.parametrize("bad", ["present", "", "VISIBLE", None])
def test_unknown_state_is_rejected(bad: Any) -> None:
    with pytest.raises(ValidationError):
        validate_step(wait_for_step(state=bad))


@pytest.mark.parametrize("interval", [0, -1, -500])
def test_non_positive_interval_is_rejected(interval: int) -> None:
    """A zero interval would hot-spin the driver; a negative one used to blow
    up mid-poll as a ``Jitter`` ValueError that ``optional`` swallowed."""
    with pytest.raises(ValidationError):
        validate_step(wait_for_step(interval=interval))


@pytest.mark.parametrize("settle", [0, -1, -1500])
def test_non_positive_settle_is_rejected(settle: int) -> None:
    with pytest.raises(ValidationError):
        validate_step(wait_for_step(settle=settle))


@pytest.mark.parametrize("timeout", [-1, -3000])
def test_negative_timeout_is_rejected(timeout: int) -> None:
    with pytest.raises(ValidationError):
        validate_step(wait_for_step(timeout=timeout))


def test_zero_timeout_is_allowed_as_a_single_check() -> None:
    assert validate_step(wait_for_step(timeout=0)).timeout == 0


@pytest.mark.parametrize(
    "option,value", [("--interval", "0"), ("--timeout", "-1"), ("--settle", "0")]
)
def test_cli_rejects_out_of_range_budgets(
    monkeypatch: pytest.MonkeyPatch, option: str, value: str
) -> None:
    monkeypatch.setattr("llm_browser.cli.build_session", lambda *a, **k: MagicMock())

    result = CliRunner().invoke(
        main, ["wait-for", "--selector", "#late", option, value]
    )

    assert result.exit_code == 2


def test_selector_is_required() -> None:
    with pytest.raises(ValidationError):
        validate_step({"name": "x", "action": "wait_for"})


# --- Action dispatch ---


def test_action_forwards_every_knob(mock_session: MagicMock) -> None:
    step = validate_step(
        wait_for_step(state="stable", timeout=900, interval=120, settle=300)
    )

    assert isinstance(execute_action(mock_session, step), VoidResult)
    mock_session.wait_for_element.assert_called_once_with(
        "#late", state="stable", timeout=900, interval=120, settle=300
    )


def test_optional_step_skips_on_timeout(mock_session: MagicMock) -> None:
    mock_session.wait_for_element.side_effect = TimeoutError(TIMEOUT_MESSAGE)
    step = validate_step(wait_for_step(state="visible", optional=True))

    result = execute_action(mock_session, step)

    assert isinstance(result, SkippedResult)
    assert TIMEOUT_MESSAGE in result.reason


# --- Flow-level failure report ---


def _run_missing_element_flow(session: MagicMock, **step_overrides: Any) -> Any:
    session.wait_for_element.side_effect = TimeoutError(TIMEOUT_MESSAGE)
    flow = load_flow_text(
        yaml.dump({"steps": [wait_for_step(state="visible", **step_overrides)]})
    )
    return run_flow(session, flow, {})


def test_timeout_fails_the_flow_with_a_full_capture(
    mock_session: MagicMock, tmp_path: Path
) -> None:
    mock_session.capture = "both"
    mock_session.take_dom_snapshot.return_value = tmp_path / "dom.html"

    result = _run_missing_element_flow(mock_session)

    assert isinstance(result, FlowError)
    assert result.step == "await_it"
    assert result.screenshot == str(tmp_path / "screenshot.png")
    assert result.dom == str(tmp_path / "dom.html")


def test_failure_report_carries_the_selector_and_state_message(
    mock_session: MagicMock,
) -> None:
    result = _run_missing_element_flow(mock_session)

    assert isinstance(result, FlowError)
    assert getattr(result.data, "message") == TIMEOUT_MESSAGE
    assert getattr(result.data, "error") == "TimeoutError"


def test_human_needed_is_reported(mock_session: MagicMock) -> None:
    from llm_browser.models import PageProbe

    mock_session.probe.return_value = PageProbe(password_visible=True)

    result = _run_missing_element_flow(mock_session)

    assert isinstance(result, FlowError)
    assert result.human_needed is True


def test_optional_missing_element_does_not_fail_the_flow(
    mock_session: MagicMock,
) -> None:
    result = _run_missing_element_flow(mock_session, optional=True)

    assert isinstance(result, FlowSuccess)


def test_successful_wait_runs_the_next_step(mock_session: MagicMock) -> None:
    flow = load_flow_text(
        yaml.dump(
            {
                "steps": [
                    wait_for_step(),
                    {"name": "hit", "action": "click", "selector": "#late"},
                ]
            }
        )
    )

    result = run_flow(mock_session, flow, {})

    assert isinstance(result, FlowSuccess)
    mock_session.wait_for_element.assert_called_once()


def test_step_survives_a_template_round_trip(mock_session: MagicMock) -> None:
    """``resolve_step`` re-validates a dumped step; a lost field would show here."""
    flow = load_flow_text(
        yaml.dump(
            {
                "params": ["target"],
                "steps": [
                    wait_for_step(selector="{{ target }}", state="hidden", interval=50)
                ],
            }
        )
    )
    step = flow.steps[0]

    execute_step(mock_session, step, flow.validate_data({"target": "#gone"}))

    mock_session.wait_for_element.assert_called_once_with(
        "#gone",
        state="hidden",
        timeout=DEFAULT_WAIT_TIMEOUT_MS,
        interval=50,
        settle=DEFAULT_SETTLE_MS,
    )


# --- CLI ---


def test_cli_reports_a_timeout_as_a_clean_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock()
    session.wait_for_element.side_effect = TimeoutError(TIMEOUT_MESSAGE)
    monkeypatch.setattr("llm_browser.cli.build_session", lambda *a, **k: session)

    result = CliRunner().invoke(main, ["wait-for", "--selector", "#late"])

    assert result.exit_code != 0
    assert TIMEOUT_MESSAGE in result.output


def test_cli_passes_every_option_through(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    monkeypatch.setattr("llm_browser.cli.build_session", lambda *a, **k: session)

    result = CliRunner().invoke(
        main,
        [
            "wait-for",
            "--selector",
            "#late",
            "--state",
            "visible",
            "--timeout",
            "1500",
            "--interval",
            "250",
            "--settle",
            "400",
        ],
    )

    assert result.exit_code == 0
    session.wait_for_element.assert_called_once_with(
        "#late", state="visible", timeout=1500, interval=250, settle=400
    )


def test_cli_rejects_an_unknown_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("llm_browser.cli.build_session", lambda *a, **k: MagicMock())

    result = CliRunner().invoke(
        main, ["wait-for", "--selector", "#late", "--state", "present"]
    )

    assert result.exit_code == 2
