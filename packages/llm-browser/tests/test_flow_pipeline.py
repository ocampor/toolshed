"""Tests for stage one (FlowSource) and stage two (build_flow)."""

import json
from pathlib import Path

import pytest
import yaml

from llm_browser.constants import FlowFormat
from llm_browser.flow_pipeline import FlowSource, build_flow
from llm_browser.models import Flow, RunFlowStep, SubFlow


def subflow_of(flow: Flow) -> SubFlow:
    step = flow.steps[0]
    assert isinstance(step, RunFlowStep)
    assert step.subflow is not None
    return step.subflow


FLOW_DOCUMENT = {
    "steps": [{"name": "s1", "action": "goto", "url": "https://example.com"}]
}
FLOW_YAML = yaml.dump(FLOW_DOCUMENT)
FLOW_JSON = json.dumps(FLOW_DOCUMENT)


@pytest.mark.parametrize(
    ("name", "expected_format"),
    [("flow.yml", "yaml"), ("flow.yaml", "yaml"), ("flow.json", "json")],
)
def test_from_path_reads_text_and_picks_the_format(
    tmp_path: Path, name: str, expected_format: FlowFormat
) -> None:
    path = tmp_path / name
    path.write_text(FLOW_JSON if expected_format == "json" else FLOW_YAML)

    source = FlowSource.from_path(path)

    assert (source.format, source.base_dir) == (expected_format, tmp_path.resolve())
    assert source.text == path.read_text()


def test_from_text_defaults_to_yaml_without_a_base_dir() -> None:
    source = FlowSource.from_text(FLOW_YAML)
    assert (source.format, source.base_dir) == ("yaml", None)


def test_build_flow_yields_the_same_model_for_both_formats() -> None:
    yaml_flow = build_flow(FlowSource.from_text(FLOW_YAML))
    json_flow = build_flow(FlowSource.from_text(FLOW_JSON, "json"))
    assert json_flow == yaml_flow


@pytest.mark.parametrize(
    ("text", "format", "message"),
    [
        ("steps: [\n  - name: x\n", "yaml", "invalid flow yaml"),
        ('{"steps": [', "json", "invalid flow json"),
    ],
)
def test_build_flow_names_the_format_in_a_parse_error(
    text: str, format: FlowFormat, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_flow(FlowSource.from_text(text, format))


# --- sub-flows inherit the parent's format ---

#: Tab-indented, so PyYAML rejects it and only a JSON parse succeeds.
TAB_INDENTED_JSON = json.dumps(FLOW_DOCUMENT, indent="\t")
JSON_PARENT = json.dumps(
    {"steps": [{"name": "c", "action": "run-flow", "flow": "child.json"}]}
)


def test_a_json_child_file_is_parsed_as_json(tmp_path: Path) -> None:
    (tmp_path / "child.json").write_text(TAB_INDENTED_JSON)
    parent = tmp_path / "parent.json"
    parent.write_text(JSON_PARENT)

    flow = build_flow(FlowSource.from_path(parent))

    assert subflow_of(flow).steps[0].name == "s1"


def test_a_mapping_child_is_parsed_in_the_parents_format() -> None:
    flow = build_flow(
        FlowSource.from_text(JSON_PARENT, "json"),
        subflows={"child.json": TAB_INDENTED_JSON},
    )
    assert subflow_of(flow).steps[0].name == "s1"


def test_a_yaml_child_file_still_loads_under_a_yaml_parent(tmp_path: Path) -> None:
    (tmp_path / "child.yaml").write_text(FLOW_YAML)
    parent = tmp_path / "parent.yaml"
    parent.write_text(
        yaml.dump(
            {"steps": [{"name": "c", "action": "run-flow", "flow": "child.yaml"}]}
        )
    )

    flow = build_flow(FlowSource.from_path(parent))

    assert subflow_of(flow).steps[0].name == "s1"


def test_a_bad_json_child_names_the_format() -> None:
    with pytest.raises(ValueError, match="invalid flow json"):
        build_flow(
            FlowSource.from_text(JSON_PARENT, "json"),
            subflows={"child.json": '{"steps": ['},
        )
