"""Where a ``run-flow`` reference's YAML text comes from.

The repository is the only piece of flow loading that differs between
consumers: the CLI reads from disk, a service reads from its own store.
"""

import asyncio
from collections.abc import Mapping
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
        # Only "there is nothing there" is a miss; a permission or I/O error
        # is a real failure and must not read as an unknown reference.
        try:
            return await asyncio.to_thread(self.path(ref).read_text)
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError) as exc:
            raise FlowNotFoundError(ref) from exc


class DictFlowRepository:
    """Flows already in hand, keyed by reference."""

    def __init__(self, flows: Mapping[str, str]) -> None:
        self.flows = flows

    async def get(self, ref: str) -> str:
        try:
            return self.flows[ref]
        except KeyError as exc:
            raise FlowNotFoundError(ref) from exc


class LayeredFlowRepository:
    """The first layer that has the reference wins.

    The usual shape is one request's own flows over a persistent store:
    ``LayeredFlowRepository(DictFlowRepository(request_flows), store)``.
    """

    def __init__(self, *layers: FlowRepository) -> None:
        self.layers = layers

    async def get(self, ref: str) -> str:
        for layer in self.layers:
            try:
                return await layer.get(ref)
            except FlowNotFoundError:
                continue
        raise FlowNotFoundError(ref)
