"""A killed or timed-out worker skips ``launched_session``'s ``finally``; this closes what it left."""

import atexit
import logging
import signal
import threading
from collections.abc import Callable
from types import FrameType
from typing import Protocol

logger = logging.getLogger(__name__)

Handler = Callable[[int, FrameType | None], object] | int | signal.Handlers | None


class Closeable(Protocol):
    def close(self) -> object: ...


class LaunchPlaceholder:
    """Keeps the registry non-empty during ``launch()``, so a signal then does not restore the handlers."""

    def close(self) -> None:
        return None


INTERRUPT_SIGNALS = (signal.SIGINT, signal.SIGTERM)

LIVE_SESSIONS: dict[int, Closeable] = {}

previous_handlers: dict[int, Handler] = {}
sweep_in_progress = False


def register_session(session: Closeable) -> None:
    LIVE_SESSIONS[id(session)] = session


def unregister_session(session: Closeable) -> None:
    LIVE_SESSIONS.pop(id(session), None)
    restore_interrupt_handlers_if_idle()


def register_launch_placeholder() -> Closeable:
    placeholder = LaunchPlaceholder()
    register_session(placeholder)
    return placeholder


def unregister_launch_placeholder(placeholder: Closeable) -> None:
    unregister_session(placeholder)


def close_stranded_sessions() -> None:
    """A re-entering signal is a no-op; an interrupt raised by one close is held until the rest close."""
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
                if to_reraise is None:
                    to_reraise = interrupt
            except Exception:  # noqa: BLE001, S110 - one session's failure is not fatal
                pass
    finally:
        sweep_in_progress = False
    # Not restore_interrupt_handlers_if_idle() here: a sweep can run while a
    # LaunchPlaceholder is the only thing registered, and closing it empties
    # the registry without meaning the launch it stands for is done.
    # Restoring is unregister_session's call — it runs once whatever was
    # actually finished (a session closed, or a launch placeholder cleared)
    # says so.
    if to_reraise is not None:
        raise to_reraise


def install_interrupt_handlers() -> None:
    """``signal.signal`` works only on the main thread; elsewhere this is a no-op."""
    if threading.current_thread() is not threading.main_thread():
        return
    if previous_handlers:
        return
    for sig in INTERRUPT_SIGNALS:
        previous_handlers[sig] = signal.getsignal(sig)
        signal.signal(sig, handle_interrupt)


def restore_interrupt_handlers_if_idle() -> None:
    """Only ``unregister_session`` calls this, so a placeholder popped mid-sweep restores nothing early."""
    if LIVE_SESSIONS or not previous_handlers:
        return
    if threading.current_thread() is not threading.main_thread():
        return
    for sig, previous in previous_handlers.items():
        signal.signal(sig, previous)
    previous_handlers.clear()


def handle_interrupt(signum: int, frame: FrameType | None) -> None:
    # Captured before the sweep: a session's close() runs arbitrary code, and
    # nothing rules out it reaching unregister_session itself, which can
    # restore (and clear) the saved handlers before this call gets to them.
    previous = previous_handlers.get(signum)
    close_stranded_sessions()
    if previous is signal.SIG_IGN:
        return
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
