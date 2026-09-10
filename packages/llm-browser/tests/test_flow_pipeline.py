"""Tests for stage one: a flow reference or text in, a resolved document out."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
import yaml

from llm_browser.flow_pipeline import resolve_flow, resolve_flow_text
from llm_browser.flow_repository import FileFlowRepository, FlowNotFoundError

CHILD_YAML = yaml.dump(
    {"steps": [{"name": "c1", "action": "click", "selector": "#child"}]}
)
BAD_YAML = "steps: [\n  - name: x\n"


def _parent_yaml(*refs: str) -> str:
    steps = [
        {"name": f"s{i}", "action": "run-flow", "flow": ref}
        for i, ref in enumerate(refs)
    ]
    return yaml.dump({"steps": steps})


class FakeRepository:
    """Records every fetch, and blocks until `concurrency` fetches are in
    flight so a serial resolver would deadlock into a timeout."""

    def __init__(self, flows: dict[str, str], concurrency: int = 1) -> None:
        self.flows = flows
        self.calls: list[str] = []
        self.barrier = asyncio.Barrier(concurrency)

    async def get(self, ref: str) -> str:
        self.calls.append(ref)
        await self.barrier.wait()
        if ref not in self.flows:
            raise FlowNotFoundError(ref)
        return self.flows[ref]


def _resolve_text(text: str, repo: Any) -> dict[str, Any]:
    return asyncio.run(resolve_flow_text(text, repo))


def test_a_flow_without_references_parses_to_its_document() -> None:
    repo = FakeRepository({})
    assert _resolve_text(CHILD_YAML, repo) == yaml.safe_load(CHILD_YAML)
    assert repo.calls == []


def test_resolve_flow_fetches_the_flow_itself() -> None:
    repo = FakeRepository({"parent": _parent_yaml("child"), "child": CHILD_YAML}, 1)
    document = asyncio.run(resolve_flow("parent", repo))
    assert document["steps"][0]["flow"] == yaml.safe_load(CHILD_YAML)
    assert repo.calls == ["parent", "child"]


def test_a_child_is_inlined_in_place_of_its_reference() -> None:
    document = _resolve_text(
        _parent_yaml("child"), FakeRepository({"child": CHILD_YAML})
    )
    assert document["steps"][0]["flow"] == yaml.safe_load(CHILD_YAML)


def test_children_are_fetched_concurrently() -> None:
    repo = FakeRepository({"a": CHILD_YAML, "b": CHILD_YAML}, concurrency=2)
    document = _resolve_text(_parent_yaml("a", "b"), repo)
    assert sorted(repo.calls) == ["a", "b"]
    assert [step["flow"] for step in document["steps"]] == [
        yaml.safe_load(CHILD_YAML)
    ] * 2


def test_a_repeated_reference_is_fetched_once() -> None:
    repo = FakeRepository({"child": CHILD_YAML}, concurrency=1)
    document = _resolve_text(_parent_yaml("child", "child"), repo)
    assert repo.calls == ["child"]
    assert document["steps"][1]["flow"] == yaml.safe_load(CHILD_YAML)


def test_a_missing_reference_surfaces_from_the_repository() -> None:
    with pytest.raises(FlowNotFoundError, match="child"):
        _resolve_text(_parent_yaml("child"), FakeRepository({}))


def test_a_child_with_its_own_reference_is_rejected() -> None:
    repo = FakeRepository({"child": _parent_yaml("grandchild")})
    with pytest.raises(ValueError, match="nested sub-flows are not allowed"):
        _resolve_text(_parent_yaml("child"), repo)


@pytest.mark.parametrize(
    ("text", "flows"),
    [(BAD_YAML, {}), (_parent_yaml("child"), {"child": BAD_YAML})],
    ids=["parent", "child"],
)
def test_bad_yaml_is_wrapped(text: str, flows: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="invalid flow yaml"):
        _resolve_text(text, FakeRepository(flows))


def test_a_document_that_is_not_a_mapping_is_rejected() -> None:
    with pytest.raises(ValueError, match="expected a mapping"):
        _resolve_text("just a string", FakeRepository({}))


@pytest.mark.parametrize(
    "steps",
    [
        [{"name": "s", "action": "click", "selector": "#a"}],
        [{"name": "s", "action": "run-flow", "flow": {"steps": []}}],
        [{"name": "s", "action": "run-flow", "flow": ""}],
        "not-a-list",
    ],
)
def test_nothing_to_resolve_leaves_the_document_alone(steps: Any) -> None:
    repo = FakeRepository({})
    document = {"steps": steps}
    assert _resolve_text(yaml.dump(document), repo) == document
    assert repo.calls == []


def test_a_file_repository_resolves_a_sibling_child(tmp_path: Path) -> None:
    (tmp_path / "child.yaml").write_text(CHILD_YAML)
    (tmp_path / "parent.yaml").write_text(_parent_yaml("child.yaml"))

    document = asyncio.run(resolve_flow("parent.yaml", FileFlowRepository(tmp_path)))

    assert document["steps"][0]["flow"] == yaml.safe_load(CHILD_YAML)
