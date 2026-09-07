"""Tests for the one-shot ``run --cdp-url`` path (cli.run_attached)."""

from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from llm_browser.cli import main, run_attached
from llm_browser.session import BrowserSession
from tests.test_attach import AttachStubDriver

CDP_URL = "http://127.0.0.1:9223"


@pytest.fixture
def base(tmp_path: Path) -> BrowserSession:
    return BrowserSession(state_dir=tmp_path, driver=AttachStubDriver())


def stub_driver(session: BrowserSession) -> AttachStubDriver:
    assert isinstance(session.driver, AttachStubDriver)
    return session.driver


def test_run_attached_attaches_runs_and_closes(base: BrowserSession) -> None:
    seen: list[BrowserSession] = []

    result = run_attached(base, CDP_URL, lambda s: seen.append(s) or "done")

    driver = stub_driver(base)
    assert driver.attach_calls == [CDP_URL]
    assert result == "done"
    assert len(driver.close_calls) == 1
    assert seen[0] is not base


def test_run_attached_closes_when_flow_raises(base: BrowserSession) -> None:
    def boom(_s: BrowserSession) -> object:
        raise RuntimeError("flow blew up")

    with pytest.raises(RuntimeError, match="flow blew up"):
        run_attached(base, CDP_URL, boom)

    assert len(stub_driver(base).close_calls) == 1


def test_run_attached_is_stateless(base: BrowserSession) -> None:
    """No state.json is read or written, so parallel runs never collide."""
    seen: list[BrowserSession] = []

    def record(session: BrowserSession) -> object:
        seen.append(session)
        assert session.stateless
        assert not session._state_file.exists()
        return None

    run_attached(base, CDP_URL, record)
    assert not seen[0]._state_file.exists()


def test_run_attached_uses_a_unique_session_id(base: BrowserSession) -> None:
    """Concurrent one-shot runs must not share a session directory."""
    ids = []
    for _ in range(2):
        run_attached(base, CDP_URL, lambda s: ids.append(s.session_id))

    assert ids[0] != ids[1]
    assert all(sid.startswith(f"{base.session_id}-") for sid in ids)


def test_run_attached_forwards_capture_and_executable(tmp_path: Path) -> None:
    base = BrowserSession(
        state_dir=tmp_path,
        driver=AttachStubDriver(),
        capture="dom",
        executable_path="/usr/bin/chromium",
    )
    seen: list[BrowserSession] = []

    run_attached(base, CDP_URL, lambda s: seen.append(s))

    assert seen[0].capture == "dom"
    assert seen[0].executable_path == "/usr/bin/chromium"


def invoke_run(
    monkeypatch: pytest.MonkeyPatch, *args: str
) -> tuple[Any, AttachStubDriver]:
    driver = AttachStubDriver()
    monkeypatch.setattr("llm_browser.session.resolve_driver", lambda _d: driver)
    monkeypatch.setattr("llm_browser.cli.run_flow", lambda *a, **k: {"ok": True})
    result = CliRunner().invoke(main, [*args, "run", "--flow", "flow.yml"])
    return result, driver


def test_run_reuses_the_attached_group_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """--cdp-url + --target-id drives the caller's tab and leaves it open."""
    result, driver = invoke_run(monkeypatch, "--cdp-url", CDP_URL, "--target-id", "ABC")

    assert result.exit_code == 0
    assert driver.attach_to_tab_calls == [(CDP_URL, "ABC")]
    assert driver.attach_calls == []
    assert driver.close_calls == []


def test_run_with_group_cdp_url_only_is_one_shot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, driver = invoke_run(monkeypatch, "--cdp-url", CDP_URL)

    assert result.exit_code == 0
    assert driver.attach_calls == [CDP_URL]
    assert len(driver.close_calls) == 1


def test_target_id_without_cdp_url_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _driver = invoke_run(monkeypatch, "--target-id", "ABC")

    assert result.exit_code == 2
    assert "--target-id requires --cdp-url" in result.output
