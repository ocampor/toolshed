"""Tests for how a `run-flow` reference becomes sub-flow YAML text."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from llm_browser.flow_files import load_flow
from llm_browser.flows import load_flow_text, subflow_refs
from llm_browser.models import RunFlowStep

CHILD_YAML = """
steps:
  - name: c1
    action: click
    selector: "#child"
"""


class MissingSubflow(LookupError):
    """Mirrors the consumer that raises from inside its own loader."""


def _flow_yaml(steps: list[dict[str, Any]], **extra: Any) -> str:
    return yaml.dump({"steps": steps, **extra})


def _parent_yaml(ref: str, name: str = "c") -> str:
    return _flow_yaml([{"name": name, "action": "run-flow", "flow": ref}])


def _child_of(flow: Any) -> Any:
    step = flow.steps[0]
    assert isinstance(step, RunFlowStep)
    assert step.subflow is not None
    return step.subflow


def _exploding_loader(ref: str) -> str:
    pytest.fail(f"loader should not be called, got {ref!r}")


# --- resolution order ---


def test_resolves_subflow_via_loader() -> None:
    flow = load_flow_text(
        _parent_yaml("registry://child"), subflow_loader=lambda r: CHILD_YAML
    )
    assert _child_of(flow).steps[0].name == "c1"


def test_loader_receives_reference() -> None:
    seen: list[str] = []

    def loader(ref: str) -> str:
        seen.append(ref)
        return CHILD_YAML

    load_flow_text(_parent_yaml("shared/login"), subflow_loader=loader)
    assert seen == ["shared/login"]


def test_text_loaded_flow_sends_file_like_ref_to_the_loader(tmp_path: Path) -> None:
    child = tmp_path / "child.yaml"
    child.write_text(
        _flow_yaml([{"name": "on_disk", "action": "click", "selector": "#d"}])
    )
    flow = load_flow_text(_parent_yaml(str(child)), subflow_loader=lambda r: CHILD_YAML)
    assert _child_of(flow).steps[0].name == "c1"


def test_load_flow_resolves_child_from_disk(tmp_path: Path) -> None:
    child = tmp_path / "child.yaml"
    child.write_text(CHILD_YAML)
    parent = tmp_path / "parent.yaml"
    parent.write_text(_parent_yaml("child.yaml"))
    assert _child_of(load_flow(parent)).steps[0].name == "c1"


def test_subflows_mapping_resolves_reference() -> None:
    flow = load_flow_text(
        _parent_yaml("registry://child"), subflows={"registry://child": CHILD_YAML}
    )
    assert _child_of(flow).steps[0].name == "c1"


def test_subflows_mapping_wins_over_the_loader() -> None:
    flow = load_flow_text(
        _parent_yaml("registry://child"),
        subflows={"registry://child": CHILD_YAML},
        subflow_loader=_exploding_loader,
    )
    assert _child_of(flow).steps[0].name == "c1"


def test_reference_absent_from_the_mapping_falls_through_to_the_loader() -> None:
    flow = load_flow_text(
        _parent_yaml("registry://other"),
        subflows={"registry://child": "steps: []"},
        subflow_loader=lambda r: CHILD_YAML,
    )
    assert _child_of(flow).steps[0].name == "c1"


def test_base_dir_resolves_child_from_disk(tmp_path: Path) -> None:
    (tmp_path / "child.yaml").write_text(CHILD_YAML)
    flow = load_flow_text(_parent_yaml("child.yaml"), base_dir=tmp_path)
    assert _child_of(flow).steps[0].name == "c1"


def test_subflows_mapping_wins_over_base_dir(tmp_path: Path) -> None:
    (tmp_path / "child.yaml").write_text(_parent_yaml("deeper", name="on_disk"))
    flow = load_flow_text(
        _parent_yaml("child.yaml"),
        subflows={"child.yaml": CHILD_YAML},
        base_dir=tmp_path,
    )
    assert _child_of(flow).steps[0].name == "c1"


def test_without_base_dir_a_sibling_ref_is_unresolvable(tmp_path: Path) -> None:
    (tmp_path / "child.yaml").write_text(CHILD_YAML)
    with pytest.raises(ValueError, match="child.yaml"):
        load_flow_text(_parent_yaml(str(tmp_path / "child.yaml")))


def test_without_loader_rejects_subflow() -> None:
    with pytest.raises(ValueError, match="subflow_loader"):
        load_flow_text(_parent_yaml("registry://x"))


def test_unresolvable_reference_is_named_in_the_error() -> None:
    with pytest.raises(ValueError, match="registry://x"):
        load_flow_text(_parent_yaml("registry://x"), subflows={"other": CHILD_YAML})


def test_loader_exception_propagates_unchanged() -> None:
    def loader(ref: str) -> str:
        raise MissingSubflow(ref)

    with pytest.raises(MissingSubflow, match="registry://x"):
        load_flow_text(_parent_yaml("registry://x"), subflow_loader=loader)


def test_rejects_nested_subflow() -> None:
    nested = _parent_yaml("deeper", name="n")
    with pytest.raises(ValueError, match="nested sub-flows"):
        load_flow_text(_parent_yaml("child"), subflow_loader=lambda r: nested)


def test_bad_yaml_raises_value_error() -> None:
    with pytest.raises(ValueError, match="invalid flow YAML"):
        load_flow_text("steps: [\n  - name: x\n")


# --- subflow_refs ---


@pytest.mark.parametrize(
    "document, expected",
    [
        ({"steps": [{"name": "s", "action": "click", "selector": "#a"}]}, []),
        ({"steps": [{"name": "c", "action": "run-flow", "flow": "one"}]}, ["one"]),
        (
            {
                "steps": [
                    {"name": "a", "action": "run-flow", "flow": "one"},
                    {"name": "b", "action": "click", "selector": "#a"},
                    {"name": "c", "action": "run-flow", "flow": "two"},
                ]
            },
            ["one", "two"],
        ),
        (
            {
                "steps": [
                    {"name": "a", "action": "run-flow", "flow": "one"},
                    {"name": "b", "action": "run-flow", "flow": "one"},
                ]
            },
            ["one"],
        ),
        ({"steps": []}, []),
        ({"steps": "not-a-list"}, []),
        ({"steps": [None, "text", {"action": "run-flow"}]}, []),
        ({"steps": [{"action": "run-flow", "flow": ""}]}, []),
        ({"steps": [{"action": "run-flow", "flow": 7}]}, []),
        ({"params": ["x"]}, []),
        ("just a string", []),
        (None, []),
    ],
)
def test_subflow_refs_cases(document: object, expected: list[str]) -> None:
    assert subflow_refs(yaml.dump(document)) == expected


def test_subflow_refs_rejects_bad_yaml() -> None:
    with pytest.raises(ValueError, match="invalid flow YAML"):
        subflow_refs("steps: [\n  - name: x\n")
