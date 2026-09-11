"""Registry sweep for sessions an interrupted run left open."""

import os
import signal
from collections.abc import Iterator
from typing import cast

import pytest
from llm_browser.session import BrowserSession

from llm_browser_conformance.interrupts import (
    LIVE_SESSIONS,
    close_stranded_sessions,
    handle_interrupt,
    install_interrupt_handlers,
    previous_handlers,
    register_session,
    unregister_session,
)


class FakeSession:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


@pytest.fixture(autouse=True)
def clean_module_state() -> Iterator[None]:
    """Every test starts from an empty registry and no rewired signals.

    A test that installs real handlers (or leaves a session registered on
    failure) must not bleed into the next one, so both are restored here
    regardless of how the test ends.
    """
    LIVE_SESSIONS.clear()
    previous_handlers.clear()
    yield
    LIVE_SESSIONS.clear()
    for sig, handler in previous_handlers.items():
        signal.signal(sig, handler)
    previous_handlers.clear()


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


def test_a_reentrant_sweep_is_a_no_op_and_the_original_continues() -> None:
    """A second signal arriving mid-sweep re-enters ``close_stranded_sessions``.

    Before the reentrancy flag, that second call cleared the registry it
    found empty-looking-enough-to-abandon while the first call was still
    partway through it, stranding whatever the first call had not reached
    yet. Simulated here by having one session's own ``close()`` call back
    into the sweep, as the nested signal handler would.
    """

    class ReentersOnClose(FakeSession):
        def close(self) -> None:
            close_stranded_sessions()
            super().close()

    first = ReentersOnClose()
    second = FakeSession()
    register_session(cast(BrowserSession, first))
    register_session(cast(BrowserSession, second))

    close_stranded_sessions()

    assert first.close_calls == 1
    assert second.close_calls == 1
    assert LIVE_SESSIONS == {}


def test_an_interrupt_raised_while_closing_one_session_waits_for_the_rest() -> None:
    class RaisesSystemExitOnClose(FakeSession):
        def close(self) -> None:
            super().close()
            raise SystemExit(130)

    interrupted = RaisesSystemExitOnClose()
    other = FakeSession()
    register_session(cast(BrowserSession, interrupted))
    register_session(cast(BrowserSession, other))

    with pytest.raises(SystemExit):
        close_stranded_sessions()

    assert interrupted.close_calls == 1
    assert other.close_calls == 1
    assert LIVE_SESSIONS == {}


def test_install_saves_and_chains_to_the_previous_handler() -> None:
    previous_calls: list[int] = []

    def spy_previous(signum: int, frame: object) -> None:
        previous_calls.append(signum)

    signal.signal(signal.SIGINT, spy_previous)
    install_interrupt_handlers()

    session = FakeSession()
    register_session(cast(BrowserSession, session))

    handle_interrupt(signal.SIGINT, None)

    assert session.close_calls == 1
    assert previous_calls == [signal.SIGINT]


def test_restoring_lets_a_later_sigint_reach_the_previous_handler_again() -> None:
    previous_calls: list[int] = []

    def spy_previous(signum: int, frame: object) -> None:
        previous_calls.append(signum)

    signal.signal(signal.SIGINT, spy_previous)
    install_interrupt_handlers()

    session = FakeSession()
    register_session(cast(BrowserSession, session))
    unregister_session(cast(BrowserSession, session))

    assert signal.getsignal(signal.SIGINT) is spy_previous


def test_a_real_sigint_closes_registered_sessions_and_chains() -> None:
    """Exercises the actual OS wiring, not just a direct call to the handler."""
    previous_calls: list[int] = []

    def spy_previous(signum: int, frame: object) -> None:
        previous_calls.append(signum)

    signal.signal(signal.SIGINT, spy_previous)
    install_interrupt_handlers()

    session = FakeSession()
    register_session(cast(BrowserSession, session))

    os.kill(os.getpid(), signal.SIGINT)

    assert session.close_calls == 1
    assert previous_calls == [signal.SIGINT]
