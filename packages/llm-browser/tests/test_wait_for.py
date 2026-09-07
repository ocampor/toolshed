"""Tests for the `wait_for` and `bring_to_front` actions."""

import time
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from llm_browser.actions import ErrorResult, VoidResult, execute_action
from llm_browser.constants import PROBE_TIMEOUT_MS
from llm_browser.models import BringToFrontStep, WaitForStep
from llm_browser.session import BrowserSession


@pytest.fixture
def session(tmp_path: object) -> BrowserSession:
    s = BrowserSession(state_dir=tmp_path)  # type: ignore[arg-type]
    s._page = MagicMock()
    return s


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Virtual clock: ``time.sleep`` advances ``time.monotonic``."""
    now = [0.0]

    def advance(seconds: float) -> None:
        now[0] += seconds

    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    monkeypatch.setattr(time, "sleep", advance)
    return now


def stub_existence(
    monkeypatch: pytest.MonkeyPatch, session: BrowserSession, results: list[bool]
) -> list[int]:
    """Make ``element_exists`` yield ``results`` (last value repeats forever).
    Returns the list of timeouts it was called with."""
    timeouts: list[int] = []
    remaining = list(results)

    def fake_exists(selector: Any, timeout: int = 3_000) -> bool:
        timeouts.append(timeout)
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    monkeypatch.setattr(session, "element_exists", fake_exists)
    return timeouts


def step(**overrides: Any) -> WaitForStep:
    params: dict[str, Any] = {
        "name": "wait",
        "action": "wait_for",
        "selector": "#logged-in",
    }
    params.update(overrides)
    return WaitForStep(**params)


def test_healthy_first_probe_returns_without_sleeping(
    session: BrowserSession, clock: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of the watchdog: a healthy page waits for nothing."""
    timeouts = stub_existence(monkeypatch, session, [True])
    result = execute_action(session, step())
    assert isinstance(result, VoidResult)
    assert timeouts == [PROBE_TIMEOUT_MS]
    assert clock[0] == pytest.approx(0.0)


def test_returns_when_selector_appears(
    session: BrowserSession, clock: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    timeouts = stub_existence(monkeypatch, session, [False, False, True])
    result = execute_action(session, step(poll_ms=1_000))
    assert isinstance(result, VoidResult)
    assert timeouts == [PROBE_TIMEOUT_MS] * 3
    assert clock[0] == pytest.approx(2.0)


def test_returns_when_selector_disappears(
    session: BrowserSession, clock: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_existence(monkeypatch, session, [True, False])
    result = execute_action(session, step(until="absent", poll_ms=500))
    assert isinstance(result, VoidResult)
    assert clock[0] == pytest.approx(0.5)


def test_timeout_returns_error_result(
    session: BrowserSession, clock: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_existence(monkeypatch, session, [False])
    result = execute_action(session, step(timeout_ms=5_000, poll_ms=1_000))
    assert isinstance(result, ErrorResult)
    assert result.error == "TimeoutError"
    assert result.step_name == "wait"
    assert clock[0] == pytest.approx(5.0)


@pytest.mark.parametrize("field", ["poll_ms", "timeout_ms"])
@pytest.mark.parametrize("value", [0, -1])
def test_rejects_non_positive_intervals(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        step(**{field: value})


# --- bring_to_front ---


def bring_to_front_step() -> BringToFrontStep:
    return BringToFrontStep(name="raise tab", action="bring_to_front")


def test_bring_to_front_raises_the_tab(session: BrowserSession) -> None:
    result = execute_action(session, bring_to_front_step())
    assert isinstance(result, VoidResult)
    assert session._page.bring_to_front.called is True  # type: ignore[union-attr]


def test_bring_to_front_swallows_driver_failure(
    session: BrowserSession, capsys: pytest.CaptureFixture[str]
) -> None:
    session._page.bring_to_front.side_effect = NotImplementedError(  # type: ignore[union-attr]
        "nodriver does not support bring_to_front"
    )
    result = execute_action(session, bring_to_front_step())
    assert isinstance(result, VoidResult)
    assert "bring_to_front failed" in capsys.readouterr().err
