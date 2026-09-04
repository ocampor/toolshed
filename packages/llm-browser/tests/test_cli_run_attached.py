"""Tests for the one-shot ``run --cdp-url`` path (cli.run_attached)."""

from pathlib import Path

import pytest

from llm_browser.cli import run_attached
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
