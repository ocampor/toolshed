"""Resolve a ``run-flow`` step's ``flow:`` reference to a flow source."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from llm_browser.flow_pipeline import FlowSource


def subflow_source(ref: str, ctx: Mapping[str, Any]) -> FlowSource | None:
    """Mapping, then loader, then ``base_dir``: only a file-loaded flow has a
    ``base_dir``, so flow text never reaches the filesystem. ``None`` means the
    context asked for no resolution at all."""
    if not {"subflows", "subflow_loader", "base_dir"} & ctx.keys():
        return None
    subflows = ctx.get("subflows")
    if subflows is not None and ref in subflows:
        return FlowSource.from_text(subflows[ref])
    loader = ctx.get("subflow_loader")
    if loader is not None:
        return FlowSource.from_text(loader(ref))
    base_dir = ctx.get("base_dir")
    if base_dir is not None:
        return FlowSource.from_path(resolve_path(ref, base_dir))
    raise ValueError(
        f"run-flow reference {ref!r}: not in subflows, "
        "no subflow_loader, and no base_dir"
    )


def resolve_path(ref: str, base_dir: Any) -> Path:
    path = Path(ref)
    if path.is_absolute():
        return path
    return Path(base_dir) / path
