"""Stage one of the flow pipeline: flow text in, a resolved flow document out.

Resolving is the only stage that does I/O — every ``run-flow`` reference is
fetched from a :class:`~llm_browser.flow_repository.FlowRepository` and
inlined, so stage two (:func:`llm_browser.flows.load_flow_document`) is pure.
"""

import asyncio
from collections.abc import Mapping
from typing import Any

import yaml

from llm_browser.flow_repository import FlowRepository


def parse_flow_yaml(text: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid flow yaml: {exc}") from exc


def flow_document(text: str) -> dict[str, Any]:
    document = parse_flow_yaml(text)
    if not isinstance(document, dict):
        raise ValueError(
            f"invalid flow yaml: expected a mapping, got {type(document).__name__}"
        )
    return document


def unresolved_run_flow_steps(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    """``run-flow`` steps whose ``flow:`` is still a reference string."""
    steps = document.get("steps")
    if not isinstance(steps, list):
        return []
    return [step for step in steps if is_unresolved_run_flow(step)]


def is_unresolved_run_flow(step: Any) -> bool:
    return (
        isinstance(step, dict)
        and step.get("action") == "run-flow"
        and isinstance(step.get("flow"), str)
        and step["flow"] != ""
    )


async def resolve_flow(ref: str, repo: FlowRepository) -> dict[str, Any]:
    return await resolve_flow_text(await repo.get(ref), repo)


async def resolve_flow_text(text: str, repo: FlowRepository) -> dict[str, Any]:
    """Replace every ``flow: <ref>`` with the referenced flow's document.

    Children are fetched concurrently, once per distinct reference, and are
    leaf-only: a child that references a flow of its own is rejected here.
    """
    document = flow_document(text)
    steps = unresolved_run_flow_steps(document)
    refs = list(dict.fromkeys(step["flow"] for step in steps))
    children = await asyncio.gather(*(child_document(ref, repo) for ref in refs))
    by_ref = dict(zip(refs, children, strict=True))
    for step in steps:
        step["flow"] = by_ref[step["flow"]]
    return document


async def child_document(ref: str, repo: FlowRepository) -> dict[str, Any]:
    document = flow_document(await repo.get(ref))
    nested = unresolved_run_flow_steps(document)
    if nested:
        raise ValueError(
            f"sub-flow {ref!r} contains a `run-flow` step "
            f"({nested[0].get('name', 'unnamed')!r}); "
            "nested sub-flows are not allowed."
        )
    return document
