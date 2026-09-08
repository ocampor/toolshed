"""Resolve a ``run-flow`` step's ``flow:`` reference to YAML text."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any


def subflow_text(ref: str, ctx: Mapping[str, Any]) -> str | None:
    """Return the YAML text of the sub-flow named by ``ref``, or
    ``None`` when the validation context asks for no resolution at all.

    Two context keys drive this, both optional:

    - ``base_dir`` — resolve a relative ``ref`` against this directory
      (what :func:`llm_browser.flows.load_flow` passes).
    - ``subflow_loader`` — a ``Callable[[str], str]`` returning the
      sub-flow's YAML text, used when ``ref`` isn't an existing file
      (what :func:`llm_browser.flows.load_flow_text` passes, so a caller
      can run flows without touching disk).

    An existing file always wins, so a text-loaded parent can still
    reference on-disk children. With neither key the reference stays
    unresolved (programmatic construction attaches ``subflow`` itself).
    """
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
        # Missing file under a base_dir: surface the FileNotFoundError at
        # load time, as before.
        return path.read_text()
    if "subflow_loader" in ctx:
        raise ValueError(
            f"run-flow reference {ref!r} is not an existing file and no "
            "`subflow_loader` was given; pass subflow_loader= to "
            "load_flow_text to resolve sub-flows in memory."
        )
    return None


def _resolve_path(ref: str, base_dir: Any) -> Path:
    path = Path(ref)
    if path.is_absolute() or base_dir is None:
        return path
    return Path(base_dir) / path
