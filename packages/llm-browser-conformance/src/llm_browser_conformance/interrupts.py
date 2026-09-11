"""Stop every session an interrupted run left open.

``launched_session`` closes its browser in a ``finally``, which a normal
exit — pass, fail, or an exception mid-scenario — always reaches. A worker
that is killed or times out mid-run bypasses that ``finally`` entirely: the
process dies without Chromium ever getting a shutdown request of its own.
Every session registers here while live, so ``atexit`` or a caught
SIGINT/SIGTERM can close what a normal exit already would have.
"""

import atexit
import logging
import signal
import threading
from collections.abc import Callable
from types import FrameType

from llm_browser.session import BrowserSession

logger = logging.getLogger(__name__)

Handler = Callable[[int, FrameType | None], object] | int | signal.Handlers | None

INTERRUPT_SIGNALS = (signal.SIGINT, signal.SIGTERM)

LIVE_SESSIONS: dict[int, BrowserSession] = {}

previous_handlers: dict[int, Handler] = {}
sweep_in_progress = False


def register_session(session: BrowserSession) -> None:
    LIVE_SESSIONS[id(session)] = session


def unregister_session(session: BrowserSession) -> None:
    LIVE_SESSIONS.pop(id(session), None)
    restore_interrupt_handlers_if_idle()


def close_stranded_sessions() -> None:
    """Close every registered session, one at a time, popped as it closes.

    A second signal during the sweep re-enters this function — the flag
    below turns that into a no-op instead of a second pass that finds an
    already-cleared registry and abandons whatever the first pass had not
    reached yet. Each session's ``close()`` is best-effort: an ordinary
    exception is swallowed so the next session still gets a turn, but a
    ``KeyboardInterrupt``/``SystemExit`` raised while closing one (the
    chained previous handler firing mid-sweep) is held until every other
    session has had its turn, then re-raised.
    """
    global sweep_in_progress
    if sweep_in_progress:
        logger.warning("close_stranded_sessions re-entered; ignoring")
        return
    sweep_in_progress = True
    to_reraise: BaseException | None = None
    try:
        while LIVE_SESSIONS:
            session_id, session = next(iter(LIVE_SESSIONS.items()))
            del LIVE_SESSIONS[session_id]
            try:
                session.close()
            except (KeyboardInterrupt, SystemExit) as interrupt:
                to_reraise = interrupt
            except Exception:  # noqa: BLE001, S110 - one session's failure is not fatal
                pass
    finally:
        sweep_in_progress = False
    restore_interrupt_handlers_if_idle()
    if to_reraise is not None:
        raise to_reraise


def install_interrupt_handlers() -> None:
    """Save and replace SIGINT/SIGTERM with a handler that sweeps first.

    ``signal.signal`` only works from the main thread; called from anywhere
    else this is a no-op; a background-thread caller has no way to receive
    these signals anyway.
    """
    if threading.current_thread() is not threading.main_thread():
        return
    if previous_handlers:
        return
    for sig in INTERRUPT_SIGNALS:
        previous_handlers[sig] = signal.getsignal(sig)
        signal.signal(sig, handle_interrupt)


def restore_interrupt_handlers_if_idle() -> None:
    """Put SIGINT/SIGTERM back once nothing is left to protect.

    Lets a pytest run keep its own Ctrl-C behaviour once the last
    ``launched_session`` in it has closed, instead of staying rewired for
    every unrelated test that follows.
    """
    if LIVE_SESSIONS or not previous_handlers:
        return
    if threading.current_thread() is not threading.main_thread():
        return
    for sig, previous in previous_handlers.items():
        signal.signal(sig, previous)
    previous_handlers.clear()


def handle_interrupt(signum: int, frame: FrameType | None) -> None:
    # Captured before the sweep: closing the last session can itself restore
    # (and clear) the saved handlers, which would otherwise erase the one
    # this call is about to chain to.
    previous = previous_handlers.get(signum)
    close_stranded_sessions()
    if callable(previous):
        previous(signum, frame)
        return
    if signum == signal.SIGINT:
        signal.default_int_handler(signum, frame)
        return
    raise SystemExit(128 + signum)


# Registered once at import: cheap and thread-unrestricted, unlike
# signal.signal above, and close_stranded_sessions() is a no-op with nothing
# registered — so this alone is a harmless, always-on fallback.
atexit.register(close_stranded_sessions)
