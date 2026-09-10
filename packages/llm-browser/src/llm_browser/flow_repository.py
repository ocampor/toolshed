"""Where a ``run-flow`` reference's YAML text comes from.

The repository is the only piece of flow loading that differs between
consumers: the CLI reads from disk, a service reads from its own store.
"""

import asyncio
from pathlib import Path
from typing import Protocol


class FlowNotFoundError(LookupError):
    """No flow text for a reference."""

    def __init__(self, ref: str) -> None:
        super().__init__(f"flow {ref!r} not found")
        self.ref = ref


class FlowRepository(Protocol):
    async def get(self, ref: str) -> str:
        """The flow's YAML text, or ``FlowNotFoundError``."""
        ...


class FileFlowRepository:
    """Refs are paths under ``base_dir``; an absolute ref is honoured as-is."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

    def path(self, ref: str) -> Path:
        ref_path = Path(ref)
        return ref_path if ref_path.is_absolute() else self.base_dir / ref_path

    async def get(self, ref: str) -> str:
        try:
            return await asyncio.to_thread(self.path(ref).read_text)
        except OSError as exc:
            raise FlowNotFoundError(ref) from exc
