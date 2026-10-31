"""The library's one file write: ``state.json`` is state, not output, so the no-output-writes guard exempts it by name."""

from pathlib import Path

from llm_browser.models import SessionInfo

STATE_FILENAME = "state.json"


class SessionState:
    """``stateless`` (``--cdp-url``) reads and writes nothing, so parallel runs never collide."""

    def __init__(self, path: Path, stateless: bool = False) -> None:
        self.path = path
        self.stateless = stateless
        self.info: SessionInfo | None = None

    def save(self, info: SessionInfo) -> None:
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
        """Clearing the file instead would strand an earlier detached browser with no pid for ``stop_detached``."""
        if recorded is None:
            self.clear()
            return
        self.save(recorded)
