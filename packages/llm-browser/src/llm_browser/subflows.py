"""Resolve a ``run-flow`` step's ``flow:`` reference to YAML text."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any


def subflow_text(ref: str, ctx: Mapping[str, Any]) -> str | None:
    """An existing file beats ``ctx["subflow_loader"]``, so a text-loaded
    parent can still reference on-disk children; ``None`` means the context
    (neither ``base_dir`` nor ``subflow_loader``) asked for no resolution."""
    if not {"base_dir", "subflow_loader"} & ctx.keys():
        return None
    base_dir = ctx.get("base_dir")
    path = _resolve_path(ref, base_dir)
    if path.is_file():
        return path.read_text()
    loader = ctx.get("subflow_loader")
    if loader is not None:
        text: str = loader(ref)
        return text
    if base_dir is not None:
        return path.read_text()  # raises FileNotFoundError, as before
    if "subflow_loader" in ctx:
        raise ValueError(
            f"run-flow reference {ref!r}: not a file and no subflow_loader given"
        )
    return None


def _resolve_path(ref: str, base_dir: Any) -> Path:
    path = Path(ref)
    if path.is_absolute() or base_dir is None:
        return path
    return Path(base_dir) / path
