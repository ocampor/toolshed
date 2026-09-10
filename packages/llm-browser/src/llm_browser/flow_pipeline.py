"""Stages one and two of the flow pipeline: flow text in, validated ``Flow``
out. Stage three — :func:`llm_browser.flows.run_flow` — takes the ``Flow``, so
every consumer builds the model itself and hands it to the runner."""

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from llm_browser.constants import (
    DEFAULT_FLOW_FORMAT,
    FLOW_FORMAT_BY_SUFFIX,
    FlowFormat,
)
from llm_browser.models import Flow

SelectorMap = dict[str, dict[str, Any]]

#: Maps a ``run-flow`` reference to the sub-flow's YAML text.
SubflowLoader = Callable[[str], str]

FLOW_PARSERS: dict[FlowFormat, Callable[[str], Any]] = {
    "yaml": yaml.safe_load,
    "json": json.loads,
}


class FlowSource(BaseModel):
    """Stage one: where a flow's text came from. ``base_dir`` is what a
    ``run-flow`` reference resolves against, so text with no directory never
    reaches the filesystem."""

    text: str
    format: FlowFormat = DEFAULT_FLOW_FORMAT
    base_dir: Path | None = None

    @classmethod
    def from_path(cls, path: str | Path) -> "FlowSource":
        resolved = Path(path).resolve()
        return cls(
            text=resolved.read_text(),
            format=flow_format_for(resolved),
            base_dir=resolved.parent,
        )

    @classmethod
    def from_text(
        cls,
        text: str,
        format: FlowFormat = DEFAULT_FLOW_FORMAT,
        base_dir: Path | None = None,
    ) -> "FlowSource":
        return cls(text=text, format=format, base_dir=base_dir)


def flow_format_for(path: Path) -> FlowFormat:
    return FLOW_FORMAT_BY_SUFFIX.get(path.suffix.lower(), DEFAULT_FLOW_FORMAT)


def parse_flow_document(source: FlowSource) -> Any:
    try:
        return FLOW_PARSERS[source.format](source.text)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid flow {source.format}: {exc}") from exc


def build_flow(
    source: FlowSource,
    *,
    subflows: Mapping[str, str] | None = None,
    subflow_loader: SubflowLoader | None = None,
    selector_map: SelectorMap | None = None,
) -> Flow:
    """Stage two. ``run-flow`` refs resolve eagerly against ``subflows``, then
    ``subflow_loader``, then the source's ``base_dir`` (``ValueError`` with none
    of them)."""
    return Flow.model_validate(
        parse_flow_document(source),
        context={
            "subflow_loader": subflow_loader,
            "selector_map": selector_map,
            "subflows": subflows,
            "base_dir": source.base_dir,
            "flow_format": source.format,
        },
    )


def subflow_refs(source: FlowSource) -> list[str]:
    """Refs without validating the steps, so a caller can fetch every child up
    front and hand them to ``build_flow(..., subflows=...)``."""
    document = parse_flow_document(source)
    steps = document.get("steps") if isinstance(document, Mapping) else None
    if not isinstance(steps, list):
        return []
    refs = (run_flow_ref(entry) for entry in steps)
    return list(dict.fromkeys(ref for ref in refs if ref is not None))


def run_flow_ref(entry: object) -> str | None:
    if not isinstance(entry, Mapping) or entry.get("action") != "run-flow":
        return None
    ref = entry.get("flow")
    return ref if isinstance(ref, str) and ref else None
