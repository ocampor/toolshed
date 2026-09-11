"""Registry sweep for sessions an interrupted run left open."""

from typing import cast

from llm_browser.session import BrowserSession

from llm_browser_conformance.interrupts import (
    LIVE_SESSIONS,
    close_stranded_sessions,
    register_session,
    unregister_session,
)


class FakeSession:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def test_close_stranded_sessions_closes_every_registered_session() -> None:
    left_open = FakeSession()
    also_left_open = FakeSession()
    register_session(cast(BrowserSession, left_open))
    register_session(cast(BrowserSession, also_left_open))

    close_stranded_sessions()

    assert left_open.close_calls == 1
    assert also_left_open.close_calls == 1
    assert LIVE_SESSIONS == {}


def test_unregister_removes_a_session_normal_close_already_handled() -> None:
    closed_normally = FakeSession()
    register_session(cast(BrowserSession, closed_normally))
    unregister_session(cast(BrowserSession, closed_normally))

    close_stranded_sessions()

    assert closed_normally.close_calls == 0


def test_a_session_that_fails_to_close_does_not_block_the_rest() -> None:
    class BreaksOnClose(FakeSession):
        def close(self) -> None:
            super().close()
            raise RuntimeError("already gone")

    broken = BreaksOnClose()
    other = FakeSession()
    register_session(cast(BrowserSession, broken))
    register_session(cast(BrowserSession, other))

    close_stranded_sessions()

    assert broken.close_calls == 1
    assert other.close_calls == 1
