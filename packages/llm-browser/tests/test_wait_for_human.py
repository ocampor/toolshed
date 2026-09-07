"""Tests for the `wait_for_human` action."""

import time
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from llm_browser.actions import ErrorResult, VoidResult, execute_action
from llm_browser.constants import (
    HUMAN_PROBE_TIMEOUT_MS,
    NTFY_URL_ENV_VAR,
    VNC_URL_ENV_VAR,
)
from llm_browser.models import WaitForHumanStep
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


@pytest.fixture
def notifications(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    sent: list[Any] = []

    def fake_urlopen(request: Any, timeout: float | None = None) -> Any:
        sent.append(request)
        response = MagicMock()
        response.__enter__.return_value = response
        return response

    monkeypatch.setenv(NTFY_URL_ENV_VAR, "https://ntfy.example.com/agents")
    monkeypatch.setenv(VNC_URL_ENV_VAR, "https://vnc.example.com")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return sent


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


def step(**overrides: Any) -> WaitForHumanStep:
    params: dict[str, Any] = {
        "name": "wait",
        "action": "wait_for_human",
        "selector": "#logged-in",
        "bring_to_front": False,
    }
    params.update(overrides)
    return WaitForHumanStep(**params)


def test_returns_when_selector_appears(
    session: BrowserSession, clock: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    timeouts = stub_existence(monkeypatch, session, [False, False, True])
    result = execute_action(session, step(poll_ms=1_000))
    assert isinstance(result, VoidResult)
    assert timeouts == [HUMAN_PROBE_TIMEOUT_MS] * 3
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


def test_notifies_once_with_vnc_click(
    session: BrowserSession,
    clock: list[float],
    notifications: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_existence(monkeypatch, session, [False, False, True])
    execute_action(session, step(message="Login needed: WSJ"))
    assert len(notifications) == 1
    assert notifications[0].data == b"Login needed: WSJ"
    assert notifications[0].headers["Click"] == "https://vnc.example.com"


def test_no_notification_without_message(
    session: BrowserSession,
    clock: list[float],
    notifications: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_existence(monkeypatch, session, [True])
    execute_action(session, step())
    assert notifications == []


def test_healthy_first_probe_pages_nobody(
    session: BrowserSession,
    clock: list[float],
    notifications: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of the watchdog: a healthy page wakes no one."""
    timeouts = stub_existence(monkeypatch, session, [True])
    result = execute_action(
        session, step(message="Login needed: WSJ", bring_to_front=True)
    )
    assert isinstance(result, VoidResult)
    assert notifications == []
    assert timeouts == [HUMAN_PROBE_TIMEOUT_MS]
    assert session._page.bring_to_front.called is False  # type: ignore[union-attr]
    assert clock[0] == pytest.approx(0.0)


@pytest.mark.parametrize("bring_to_front", [True, False])
def test_bring_to_front_flag(
    session: BrowserSession,
    clock: list[float],
    monkeypatch: pytest.MonkeyPatch,
    bring_to_front: bool,
) -> None:
    stub_existence(monkeypatch, session, [False, True])
    execute_action(session, step(bring_to_front=bring_to_front))
    page = session._page
    assert page.bring_to_front.called is bring_to_front  # type: ignore[union-attr]


def test_bring_to_front_failure_does_not_abort_wait(
    session: BrowserSession,
    clock: list[float],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session._page.bring_to_front.side_effect = NotImplementedError(  # type: ignore[union-attr]
        "nodriver does not support bring_to_front"
    )
    stub_existence(monkeypatch, session, [False, True])
    result = execute_action(session, step(bring_to_front=True))
    assert isinstance(result, VoidResult)
    assert "bring_to_front failed" in capsys.readouterr().err


def test_notify_failure_does_not_abort_wait(
    session: BrowserSession,
    clock: list[float],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A transient ntfy outage must not cancel a 30-minute human wait."""
    monkeypatch.delenv(NTFY_URL_ENV_VAR, raising=False)
    stub_existence(monkeypatch, session, [False, True])
    result = execute_action(session, step(message="Login needed: WSJ"))
    assert isinstance(result, VoidResult)
    assert "notification failed" in capsys.readouterr().err


@pytest.mark.parametrize("field", ["poll_ms", "timeout_ms"])
@pytest.mark.parametrize("value", [0, -1])
def test_rejects_non_positive_intervals(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        step(**{field: value})
