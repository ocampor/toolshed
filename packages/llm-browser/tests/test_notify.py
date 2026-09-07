"""Tests for ntfy notifications and the `notify` action."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from llm_browser.actions import ErrorResult, SkippedResult, VoidResult, execute_action
from llm_browser.constants import (
    NTFY_TOKEN_ENV_VAR,
    NTFY_URL_ENV_VAR,
    VNC_URL_ENV_VAR,
)
from llm_browser.models import NotifyStep
from llm_browser.notify import NotifyError, send_notification
from llm_browser.session import BrowserSession

TOPIC = "https://ntfy.example.com/agents"


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Capture the Request objects passed to urlopen."""
    requests: list[Any] = []

    def fake_urlopen(request: Any, timeout: float | None = None) -> Any:
        requests.append(request)
        response = MagicMock()
        response.__enter__.return_value = response
        return response

    monkeypatch.setenv(NTFY_URL_ENV_VAR, TOPIC)
    monkeypatch.delenv(NTFY_TOKEN_ENV_VAR, raising=False)
    monkeypatch.delenv(VNC_URL_ENV_VAR, raising=False)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return requests


@pytest.fixture
def session(tmp_path: object) -> BrowserSession:
    s = BrowserSession(state_dir=tmp_path)  # type: ignore[arg-type]
    s._page = MagicMock()
    return s


def test_send_notification_posts_message(sent: list[Any]) -> None:
    send_notification("all done")
    request = sent[0]
    assert request.full_url == TOPIC
    assert request.get_method() == "POST"
    assert request.data == b"all done"
    assert "Title" not in request.headers
    assert "Click" not in request.headers


def test_send_notification_sets_optional_headers(sent: list[Any]) -> None:
    send_notification("hi", title="Login", priority=4, click="https://vnc.local")
    headers = sent[0].headers
    assert headers["Title"] == "Login"
    assert headers["Priority"] == "4"
    assert headers["Click"] == "https://vnc.local"


def test_send_notification_uses_bearer_token(
    sent: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(NTFY_TOKEN_ENV_VAR, "tk_123")
    send_notification("hi")
    assert sent[0].headers["Authorization"] == "Bearer tk_123"


def test_click_defaults_to_vnc_url(
    sent: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(VNC_URL_ENV_VAR, "https://vnc.example.com")
    send_notification("hi")
    assert sent[0].headers["Click"] == "https://vnc.example.com"


def test_explicit_click_wins_over_vnc_url(
    sent: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(VNC_URL_ENV_VAR, "https://vnc.example.com")
    send_notification("hi", click="https://elsewhere")
    assert sent[0].headers["Click"] == "https://elsewhere"


def test_missing_url_raises_notify_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(NTFY_URL_ENV_VAR, raising=False)
    with pytest.raises(NotifyError):
        send_notification("hi")


def test_transport_failure_raises_notify_error(
    sent: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(request: Any, timeout: float | None = None) -> Any:
        raise OSError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(NotifyError):
        send_notification("hi")


def test_notify_action(session: BrowserSession, sent: list[Any]) -> None:
    step = NotifyStep(name="page me", action="notify", message="hello", title="T")
    assert isinstance(execute_action(session, step), VoidResult)
    assert sent[0].data == b"hello"
    assert sent[0].headers["Title"] == "T"


def test_notify_action_without_url_returns_error(
    session: BrowserSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(NTFY_URL_ENV_VAR, raising=False)
    step = NotifyStep(name="page me", action="notify", message="hello")
    result = execute_action(session, step)
    assert isinstance(result, ErrorResult)
    assert result.error == "NotifyError"


def test_notify_action_optional_is_skipped(
    session: BrowserSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(NTFY_URL_ENV_VAR, raising=False)
    step = NotifyStep(name="s", action="notify", message="hello", optional=True)
    assert isinstance(execute_action(session, step), SkippedResult)
