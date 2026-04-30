"""Filesystem path helpers shared across actions and session."""

from pathlib import Path


def prepare_output_path(path: str | Path) -> Path:
    """Coerce ``path`` to a ``Path`` and ensure its parent directory
    exists. Used by every action that writes a caller-controlled file
    (screenshot, dom, download) so the caller can pass paths like
    ``out/run_<ts>/<id>/turn.html`` without having to mkdir first."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    return out
