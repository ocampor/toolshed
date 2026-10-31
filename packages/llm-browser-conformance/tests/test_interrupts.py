import signal
import subprocess
import sys
from collections.abc import Iterator

import pytest

from llm_browser_conformance.interrupts import (
    LIVE_SESSIONS,
    close_stranded_sessions,
    handle_interrupt,
    install_interrupt_handlers,
    previous_handlers,
    register_launch_placeholder,
    register_session,
    unregister_launch_placeholder,
    unregister_session,
)


class FakeSession:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


@pytest.fixture(autouse=True)
def clean_module_state() -> Iterator[None]:
    # A test that installs real handlers or leaves a session registered must not bleed into the next.
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
    register_session(left_open)
    register_session(also_left_open)

    close_stranded_sessions()

    assert left_open.close_calls == 1
    assert also_left_open.close_calls == 1
    assert LIVE_SESSIONS == {}


def test_unregister_removes_a_session_normal_close_already_handled() -> None:
    closed_normally = FakeSession()
    register_session(closed_normally)
    unregister_session(closed_normally)

    close_stranded_sessions()

    assert closed_normally.close_calls == 0


def test_a_session_that_fails_to_close_does_not_block_the_rest() -> None:
    class BreaksOnClose(FakeSession):
        def close(self) -> None:
            super().close()
            raise RuntimeError("already gone")

    broken = BreaksOnClose()
    other = FakeSession()
    register_session(broken)
    register_session(other)

    close_stranded_sessions()

    assert broken.close_calls == 1
    assert other.close_calls == 1


def test_a_reentrant_sweep_is_a_no_op_and_the_original_continues() -> None:
    # A nested signal re-entering the sweep once cleared the registry the first call was still walking.

    class ReentersOnClose(FakeSession):
        def close(self) -> None:
            close_stranded_sessions()
            super().close()

    first = ReentersOnClose()
    second = FakeSession()
    register_session(first)
    register_session(second)

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
    register_session(interrupted)
    register_session(other)

    with pytest.raises(SystemExit):
        close_stranded_sessions()

    assert interrupted.close_calls == 1
    assert other.close_calls == 1
    assert LIVE_SESSIONS == {}


def test_the_first_interrupt_seen_wins_over_a_later_one() -> None:
    # Last-write-wins would drop whichever interrupt type raised first.

    class RaisesKeyboardInterruptOnClose(FakeSession):
        def close(self) -> None:
            super().close()
            raise KeyboardInterrupt

    class RaisesSystemExitOnClose(FakeSession):
        def close(self) -> None:
            super().close()
            raise SystemExit(130)

    first = RaisesKeyboardInterruptOnClose()
    second = RaisesSystemExitOnClose()
    register_session(first)
    register_session(second)

    with pytest.raises(KeyboardInterrupt):
        close_stranded_sessions()

    assert first.close_calls == 1
    assert second.close_calls == 1


def test_install_saves_and_chains_to_the_previous_handler() -> None:
    previous_calls: list[int] = []

    def spy_previous(signum: int, frame: object) -> None:
        previous_calls.append(signum)

    signal.signal(signal.SIGINT, spy_previous)
    install_interrupt_handlers()

    session = FakeSession()
    register_session(session)

    handle_interrupt(signal.SIGINT, None)

    assert session.close_calls == 1
    assert previous_calls == [signal.SIGINT]


def test_a_previously_ignored_signal_stays_ignored_after_the_sweep() -> None:
    # SIG_IGN is neither callable nor the default; it must not fall through to raising.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    install_interrupt_handlers()

    session = FakeSession()
    register_session(session)

    handle_interrupt(signal.SIGINT, None)

    assert session.close_calls == 1


def test_restoring_lets_a_later_sigint_reach_the_previous_handler_again() -> None:
    previous_calls: list[int] = []

    def spy_previous(signum: int, frame: object) -> None:
        previous_calls.append(signum)

    signal.signal(signal.SIGINT, spy_previous)
    install_interrupt_handlers()

    session = FakeSession()
    register_session(session)
    unregister_session(session)

    assert signal.getsignal(signal.SIGINT) is spy_previous


def test_a_sweep_during_launch_keeps_handlers_installed_for_the_real_session() -> None:
    # The placeholder keeps the registry non-empty until the real session registers.
    signal.signal(signal.SIGINT, lambda signum, frame: None)
    install_interrupt_handlers()

    placeholder = register_launch_placeholder()
    close_stranded_sessions()  # a signal arriving mid-launch
    assert signal.getsignal(signal.SIGINT) is handle_interrupt

    # The real session is registered before the placeholder is dropped —
    # the same order launched_session uses — so the registry is never
    # empty in between and no restore is triggered by either step.
    session = FakeSession()
    register_session(session)
    unregister_launch_placeholder(placeholder)

    handle_interrupt(signal.SIGINT, None)

    assert session.close_calls == 1


REAL_SIGINT_SCRIPT = """
import os
import signal

from llm_browser_conformance.interrupts import install_interrupt_handlers, register_session

previous_calls = []


def spy_previous(signum, frame):
    previous_calls.append(signum)


class FakeSession:
    def __init__(self):
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


signal.signal(signal.SIGINT, spy_previous)
install_interrupt_handlers()

session = FakeSession()
register_session(session)

os.kill(os.getpid(), signal.SIGINT)

print(session.close_calls, len(previous_calls))
"""


def test_a_real_sigint_closes_registered_sessions_and_chains() -> None:
    # Own process: a real SIGINT can arrive late and land in a later test's signal state.
    result = subprocess.run(
        [sys.executable, "-c", REAL_SIGINT_SCRIPT],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )

    assert result.stdout.strip() == "1 1"
