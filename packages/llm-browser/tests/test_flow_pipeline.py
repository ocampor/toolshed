"""Tests for stage one (FlowSource) and stage two (build_flow)."""

import json
from pathlib import Path

import pytest
import yaml

from llm_browser.constants import FlowFormat
from llm_browser.flow_pipeline import FlowSource, build_flow

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


@pytest.mark.parametrize(
    "source",
    [
        FlowSource.from_text(FLOW_YAML),
        FlowSource.from_text(FLOW_JSON, "json"),
    ],
)
def test_build_flow_yields_the_same_model_for_both_formats(
    source: FlowSource,
) -> None:
    assert build_flow(source) == build_flow(FlowSource.from_text(FLOW_YAML))


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


def test_build_flow_resolves_a_subflow_from_the_source_base_dir(
    tmp_path: Path,
) -> None:
    (tmp_path / "child.json").write_text(FLOW_JSON)
    parent = tmp_path / "parent.json"
    parent.write_text(
        json.dumps(
            {"steps": [{"name": "c", "action": "run-flow", "flow": "child.json"}]}
        )
    )

    flow = build_flow(FlowSource.from_path(parent))

    assert len(flow.steps) == 1
