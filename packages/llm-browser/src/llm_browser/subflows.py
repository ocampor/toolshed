"""Resolve a ``run-flow`` step's ``flow:`` reference to YAML text."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any


def subflow_text(ref: str, ctx: Mapping[str, Any]) -> str | None:
    """Mapping, then loader, then ``base_dir``: only a file-loaded flow has a
    ``base_dir``, so flow text never reaches the filesystem. ``None`` means the
    context asked for no resolution at all."""
    if not {"subflows", "subflow_loader", "base_dir"} & ctx.keys():
        return None
    subflows = ctx.get("subflows")
    if subflows is not None and ref in subflows:
        from_mapping: str = subflows[ref]
        return from_mapping
    loader = ctx.get("subflow_loader")
    if loader is not None:
        loaded: str = loader(ref)
        return loaded
    base_dir = ctx.get("base_dir")
    if base_dir is not None:
        return resolve_path(ref, base_dir).read_text()
    raise ValueError(
        f"run-flow reference {ref!r}: not in subflows, "
        "no subflow_loader, and no base_dir"
    )


def resolve_path(ref: str, base_dir: Any) -> Path:
    path = Path(ref)
    if path.is_absolute():
        return path
    return Path(base_dir) / path
