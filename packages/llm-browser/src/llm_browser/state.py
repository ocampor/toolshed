"""Where a session records the browser it is driving.

The one place in the library that writes a file, and the reason it is its own
module: ``state.json`` is *state*, not output. It is how a later process finds
a detached browser again, and the no-output-writes guard
(``tests/test_no_output_writes.py``) exempts this file by name rather than
exempting all 600 lines of ``session.py``.
"""

from pathlib import Path

from llm_browser.models import SessionInfo

STATE_FILENAME = "state.json"


class SessionState:
    """The recorded :class:`SessionInfo`, in memory and (unless stateless) on disk.

    ``stateless`` is the ``--cdp-url`` case: the caller addresses the tab
    itself, so nothing is read from or written to disk and parallel runs
    against one browser never collide.
    """

    def __init__(self, path: Path, stateless: bool = False) -> None:
        self.path = path
        self.stateless = stateless
        self.info: SessionInfo | None = None

    def save(self, info: SessionInfo) -> None:
        """Record the live session; persist it too unless stateless."""
        self.info = info
        if self.stateless:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(info.model_dump_json())

    def load(self) -> SessionInfo | None:
        if self.info is not None or self.stateless:
            return self.info
        if not self.path.exists():
            return None
        return SessionInfo.model_validate_json(self.path.read_text())

    def clear(self) -> None:
        self.info = None
        if not self.stateless and self.path.exists():
            self.path.unlink()

    def restore(self, recorded: SessionInfo | None) -> None:
        """Put back what was on disk before a launch that did not complete.

        Clearing the file instead would strand an *earlier* detached browser
        with no pid anywhere for ``stop_detached`` to kill.
        """
        if recorded is None:
            self.clear()
            return
        self.save(recorded)
