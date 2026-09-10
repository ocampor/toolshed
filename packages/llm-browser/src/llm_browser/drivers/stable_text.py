"""Python-side text-stability poll: the fallback for drivers without one."""

import time
from typing import Callable


def poll_stable_text(
    read: Callable[[], str | None], quiet_ms: int, timeout_ms: int
) -> str | None:
    """Read until the text stops changing for ``quiet_ms``; ``None`` on timeout.

    Each iteration crosses the transport. On Chromium/CDP that is a
    distinctive repeated ``Runtime.callFunctionOn`` pattern which
    Runtime-traffic detectors can fingerprint, so a driver that can run the
    same loop inside the page should.
    """
    poll_s = 0.25
    quiet_s = quiet_ms / 1000.0
    deadline = time.monotonic() + timeout_ms / 1000.0
    last_text = read() or ""
    last_change = time.monotonic()
    while time.monotonic() < deadline:
        time.sleep(poll_s)
        text = read() or ""
        now = time.monotonic()
        if text != last_text:
            last_text, last_change = text, now
        elif now - last_change >= quiet_s:
            return text
    return None
