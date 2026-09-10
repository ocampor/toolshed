"""Tests for the repository behind every `run-flow` reference."""

import asyncio
from pathlib import Path

import pytest

from llm_browser.flow_repository import FileFlowRepository, FlowNotFoundError

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
