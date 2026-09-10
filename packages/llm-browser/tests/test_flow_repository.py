"""Tests for the repository behind every `run-flow` reference."""

import asyncio
import os
from pathlib import Path

import pytest

from llm_browser.flow_repository import (
    DictFlowRepository,
    FileFlowRepository,
    FlowNotFoundError,
    LayeredFlowRepository,
)

FLOW_YAML = "steps: []\n"


def test_relative_ref_reads_under_the_base_dir(tmp_path: Path) -> None:
    (tmp_path / "child.yaml").write_text(FLOW_YAML)
    repo = FileFlowRepository(tmp_path)
    assert asyncio.run(repo.get("child.yaml")) == FLOW_YAML


def test_absolute_ref_ignores_the_base_dir(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    child = elsewhere / "child.yaml"
    child.write_text(FLOW_YAML)
    repo = FileFlowRepository(tmp_path / "base")
    assert asyncio.run(repo.get(str(child))) == FLOW_YAML


def test_nested_relative_ref(tmp_path: Path) -> None:
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "login.yaml").write_text(FLOW_YAML)
    repo = FileFlowRepository(tmp_path)
    assert asyncio.run(repo.get("shared/login.yaml")) == FLOW_YAML


def test_missing_ref_raises_flow_not_found(tmp_path: Path) -> None:
    repo = FileFlowRepository(tmp_path)
    with pytest.raises(FlowNotFoundError, match="missing.yaml"):
        asyncio.run(repo.get("missing.yaml"))


def test_file_repository_propagates_a_permission_error(tmp_path: Path) -> None:
    """An unreadable file is a real failure, not an unknown reference."""
    if os.geteuid() == 0:
        pytest.skip("root reads regardless of mode")
    child = tmp_path / "child.yaml"
    child.write_text(FLOW_YAML)
    child.chmod(0o000)
    with pytest.raises(PermissionError):
        asyncio.run(FileFlowRepository(tmp_path).get("child.yaml"))


# --- DictFlowRepository ---


def test_dict_repository_returns_a_known_flow() -> None:
    repo = DictFlowRepository({"child": FLOW_YAML})
    assert asyncio.run(repo.get("child")) == FLOW_YAML


def test_dict_repository_misses_an_unknown_flow() -> None:
    with pytest.raises(FlowNotFoundError, match="child"):
        asyncio.run(DictFlowRepository({}).get("child"))


# --- LayeredFlowRepository ---


def test_the_first_layer_with_the_reference_wins(tmp_path: Path) -> None:
    (tmp_path / "child.yaml").write_text("steps: [{name: on-disk}]\n")
    repo = LayeredFlowRepository(
        DictFlowRepository({"child.yaml": FLOW_YAML}),
        FileFlowRepository(tmp_path),
    )
    assert asyncio.run(repo.get("child.yaml")) == FLOW_YAML


def test_a_later_layer_answers_what_the_first_one_lacks(tmp_path: Path) -> None:
    (tmp_path / "child.yaml").write_text(FLOW_YAML)
    repo = LayeredFlowRepository(
        DictFlowRepository({"other": "steps: []\n"}),
        FileFlowRepository(tmp_path),
    )
    assert asyncio.run(repo.get("child.yaml")) == FLOW_YAML


def test_a_miss_in_every_layer_names_the_reference(tmp_path: Path) -> None:
    repo = LayeredFlowRepository(DictFlowRepository({}), FileFlowRepository(tmp_path))
    with pytest.raises(FlowNotFoundError, match="child.yaml"):
        asyncio.run(repo.get("child.yaml"))


def test_no_layers_is_a_miss() -> None:
    with pytest.raises(FlowNotFoundError, match="child"):
        asyncio.run(LayeredFlowRepository().get("child"))


def test_another_failure_in_a_layer_propagates() -> None:
    class BrokenRepository:
        async def get(self, ref: str) -> str:
            raise RuntimeError("store is down")

    repo = LayeredFlowRepository(BrokenRepository(), DictFlowRepository({"c": "s"}))
    with pytest.raises(RuntimeError, match="store is down"):
        asyncio.run(repo.get("c"))
