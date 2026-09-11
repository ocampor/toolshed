"""Stop every session an interrupted run left open.

``launched_session`` closes its browser in a ``finally``, which a normal
exit — pass, fail, or an exception mid-scenario — always reaches. A worker
that is killed or times out mid-run bypasses that ``finally`` entirely: the
process dies without Chromium ever getting a shutdown request of its own.
Every session registers here while live, so ``atexit`` or a caught
SIGINT/SIGTERM can close what a normal exit already would have.
"""

import atexit
import signal
import sys
from types import FrameType

from llm_browser.session import BrowserSession

LIVE_SESSIONS: dict[int, BrowserSession] = {}

_handlers_installed = False


def register_session(session: BrowserSession) -> None:
    LIVE_SESSIONS[id(session)] = session


def unregister_session(session: BrowserSession) -> None:
    LIVE_SESSIONS.pop(id(session), None)


def close_stranded_sessions() -> None:
    """Close every registered session, one at a time.

    The atexit hook and the signal handler both call this directly, so a
    session that fails to close must never stop the rest from getting the
    same chance — the whole point is a best-effort sweep, not a report.
    """
    sessions = list(LIVE_SESSIONS.values())
    LIVE_SESSIONS.clear()
    for session in sessions:
        try:
            session.close()
        except Exception:  # noqa: BLE001, S110 - best-effort cleanup, never re-raise
            pass


def install_interrupt_handlers() -> None:
    """Wire the atexit hook and SIGINT/SIGTERM once per process."""
    global _handlers_installed
    if _handlers_installed:
        return
    atexit.register(close_stranded_sessions)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handle_interrupt)
    _handlers_installed = True


def _handle_interrupt(signum: int, frame: FrameType | None) -> None:
    close_stranded_sessions()
    sys.exit(128 + signum)
