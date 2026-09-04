"""Tests for the one-shot ``run --cdp-url`` path (cli.run_attached)."""

from pathlib import Path

import pytest

from llm_browser.cli import run_attached
from llm_browser.session import BrowserSession
from tests.test_attach import AttachStubDriver

CDP_URL = "http://127.0.0.1:9223"


@pytest.fixture
def base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BrowserSession:
    monkeypatch.setattr("llm_browser.cli.DEFAULT_STATE_DIR", tmp_path / "state")
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


def test_run_attached_uses_a_fresh_state_dir(
    base: BrowserSession, tmp_path: Path
) -> None:
    """No state.json is reused or left behind, so parallel runs don't collide."""
    state_dirs: list[Path] = []

    def record(session: BrowserSession) -> object:
        state_dirs.append(session.session_dir)
        assert session._state_file.exists()
        return None

    run_attached(base, CDP_URL, record)
    run_attached(base, CDP_URL, record)

    assert state_dirs[0] != state_dirs[1]
    assert not any(d.exists() for d in state_dirs)
