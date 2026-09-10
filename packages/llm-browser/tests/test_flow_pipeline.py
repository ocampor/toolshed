"""Tests for stage one (FlowSource) and stage two (build_flow)."""

from pathlib import Path

import pytest
import yaml

from llm_browser.flow_pipeline import FlowSource, build_flow
from llm_browser.models import Flow, RunFlowStep, SubFlow

FLOW_DOCUMENT = {
    "steps": [{"name": "s1", "action": "goto", "url": "https://example.com"}]
}
FLOW_YAML = yaml.dump(FLOW_DOCUMENT)
PARENT_YAML = yaml.dump(
    {"steps": [{"name": "c", "action": "run-flow", "flow": "child.yaml"}]}
)


def subflow_of(flow: Flow) -> SubFlow:
    step = flow.steps[0]
    assert isinstance(step, RunFlowStep)
    assert step.subflow is not None
    return step.subflow


@pytest.mark.parametrize("name", ["flow.yml", "flow.yaml", "flow.txt"])
def test_from_path_reads_the_text_and_takes_its_directory(
    tmp_path: Path, name: str
) -> None:
    path = tmp_path / name
    path.write_text(FLOW_YAML)

    source = FlowSource.from_path(path)

    assert (source.text, source.base_dir) == (FLOW_YAML, tmp_path.resolve())


def test_from_text_keeps_the_text_off_the_filesystem() -> None:
    source = FlowSource.from_text(FLOW_YAML)
    assert (source.text, source.base_dir) == (FLOW_YAML, None)


def test_build_flow_validates_the_document() -> None:
    flow = build_flow(FlowSource.from_text(FLOW_YAML))
    assert flow.steps[0].name == "s1"


def test_build_flow_names_the_format_in_a_parse_error() -> None:
    with pytest.raises(ValueError, match="invalid flow yaml"):
        build_flow(FlowSource.from_text("steps: [\n  - name: x\n"))


# --- sub-flows ---


def test_a_child_file_resolves_against_the_source_base_dir(tmp_path: Path) -> None:
    (tmp_path / "child.yaml").write_text(FLOW_YAML)
    parent = tmp_path / "parent.yaml"
    parent.write_text(PARENT_YAML)

    flow = build_flow(FlowSource.from_path(parent))

    assert subflow_of(flow).steps[0].name == "s1"


def test_a_mapping_child_is_parsed_as_yaml() -> None:
    flow = build_flow(
        FlowSource.from_text(PARENT_YAML), subflows={"child.yaml": FLOW_YAML}
    )
    assert subflow_of(flow).steps[0].name == "s1"


def test_a_bad_child_names_the_format() -> None:
    with pytest.raises(ValueError, match="invalid flow yaml"):
        build_flow(
            FlowSource.from_text(PARENT_YAML),
            subflows={"child.yaml": "steps: [\n  - name: x\n"},
        )
