"""Tests for selector map loading, the refs a flow names, and the substitution
that happens as a step runs."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from llm_browser.flows import load_flow_document, run_flow
from llm_browser.models import Flow, FlowData, FlowSuccess, Step, validate_step
from llm_browser.selector_map import (
    MissingSelectorsError,
    load_selector_map,
    missing_selectors,
    selector_refs,
)
from llm_browser.selectors import IdSelector, parse_selector
from llm_browser.steps import resolve_step


def _write_map(tmp_path: Path) -> Path:
    path = tmp_path / "selector_map.yaml"
    path.write_text(
        yaml.dump(
            {
                "invoice": {
                    "rfc": {"id": "135textboxautocomplete55"},
                    "cp": {"id": "135textbox61"},
                },
                "declaracion": {
                    "copropiedad": {"id": "457select7"},
                },
            }
        )
    )
    return path


def test_load_selector_map(tmp_path: Path) -> None:
    path = _write_map(tmp_path)
    flat = load_selector_map(path)
    assert flat["invoice.rfc"] == {"id": "135textboxautocomplete55"}
    assert flat["invoice.cp"] == {"id": "135textbox61"}
    assert flat["declaracion.copropiedad"] == {"id": "457select7"}


# --- what a flow asks for ---

DOCUMENT: dict[str, Any] = {
    "steps": [
        {"name": "a", "action": "click", "ref": "ui.button"},
        {"name": "b", "action": "click", "selector": {"ref": "ui.logo"}},
        {"name": "c", "fields": [{"type": "text", "ref": "form.rfc"}]},
        {"name": "d", "read": {"cp": {"ref": "form.cp", "attribute": "value"}}},
        {
            "name": "child",
            "action": "run-flow",
            "flow": {"steps": [{"name": "e", "action": "click", "ref": "child.ok"}]},
            "data": {"ref": "INV-1"},
        },
        {"name": "dup", "action": "click", "ref": "ui.button"},
    ]
}
DOCUMENT_REFS = ["child.ok", "form.cp", "form.rfc", "ui.button", "ui.logo"]

FULL_MAP: dict[str, Any] = {ref: {"id": ref} for ref in DOCUMENT_REFS}


def test_a_flow_with_refs_validates_with_no_map_and_names_every_ref_once() -> None:
    """Step, `selector:`, `fields[]`, `read[]` and sub-flow sites, sorted and
    deduplicated; a `run-flow` `data:` value is not a ref."""
    assert selector_refs(load_flow_document(DOCUMENT)) == DOCUMENT_REFS


def test_a_flow_without_refs_names_none() -> None:
    flow = load_flow_document(
        {"steps": [{"name": "s", "action": "click", "selector": "#a"}]}
    )
    assert selector_refs(flow) == []


def test_a_step_level_ref_wins_over_a_selector_key_ref() -> None:
    flow = load_flow_document(
        {
            "steps": [
                {
                    "name": "s",
                    "action": "click",
                    "ref": "ui.a",
                    "selector": {"ref": "ui.b"},
                }
            ]
        }
    )
    assert selector_refs(flow) == ["ui.a"]


def test_missing_selectors_lists_every_absent_ref_at_once() -> None:
    flow = load_flow_document(DOCUMENT)
    assert missing_selectors(flow, {"ui.button": {"id": "b"}}) == [
        "child.ok",
        "form.cp",
        "form.rfc",
        "ui.logo",
    ]


@pytest.mark.parametrize("dropped", DOCUMENT_REFS)
def test_dropping_any_ref_from_the_map_is_reported_by_name(dropped: str) -> None:
    partial = {ref: spec for ref, spec in FULL_MAP.items() if ref != dropped}
    assert missing_selectors(load_flow_document(DOCUMENT), partial) == [dropped]


def test_a_full_map_leaves_nothing_missing() -> None:
    assert missing_selectors(load_flow_document(DOCUMENT), FULL_MAP) == []


# --- substitution at step time ---


def _resolved(step: dict[str, Any], selector_map: dict[str, Any]) -> Step:
    return resolve_step(validate_step(step), FlowData(), selector_map)


@pytest.mark.parametrize("value", ["text=Aside", {"id": "X"}, {"css": ".x"}])
def test_a_map_value_lands_on_the_step_its_fields_and_its_read_entries(
    value: Any,
) -> None:
    """A string value is the selector string — `text=Aside` must not be
    indexed like a mapping."""
    step = _resolved(
        {
            "name": "s",
            "action": "click",
            "ref": "ui.x",
            "fields": [{"ref": "ui.x"}],
            "read": {"k": {"ref": "ui.x"}},
        },
        {"ui.x": value},
    )
    expected = parse_selector(value)
    assert step.selector == expected  # type: ignore[union-attr]
    assert step.fields[0].selector == expected
    assert step.read["k"].selector == expected


def test_resolving_a_step_leaves_the_flows_own_step_alone() -> None:
    flow = load_flow_document(
        {"steps": [{"name": "s", "action": "click", "ref": "ui.x"}]}
    )
    resolve_step(flow.steps[0], FlowData(), {"ui.x": "#once"})
    assert selector_refs(flow) == ["ui.x"]


# --- substitution over a whole run ---


def _click_flow(ref: str = "ui.x") -> Flow:
    return load_flow_document({"steps": [{"name": "s", "action": "click", "ref": ref}]})


def _clicked(session: MagicMock) -> Any:
    return session.click.call_args.args[0]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("text=Go", "text=Go"), ({"id": "b"}, IdSelector(id="b"))],
)
def test_a_run_resolves_each_ref_from_the_map(
    mock_session: MagicMock, value: Any, expected: Any
) -> None:
    result = run_flow(mock_session, _click_flow(), {}, selector_map={"ui.x": value})
    assert isinstance(result, FlowSuccess)
    assert _clicked(mock_session) == expected


def test_a_sub_flows_refs_resolve_from_the_same_map(mock_session: MagicMock) -> None:
    flow = load_flow_document(
        {
            "steps": [
                {
                    "name": "child",
                    "action": "run-flow",
                    "flow": {
                        "steps": [{"name": "s", "action": "click", "ref": "child.ok"}]
                    },
                }
            ]
        }
    )
    result = run_flow(mock_session, flow, {}, selector_map={"child.ok": {"id": "deep"}})
    assert isinstance(result, FlowSuccess)
    assert _clicked(mock_session) == IdSelector(id="deep")


@pytest.mark.parametrize("selector_map", [None, {"other.ref": "#a"}])
def test_a_run_with_an_unresolved_ref_raises(
    mock_session: MagicMock, selector_map: Any
) -> None:
    with pytest.raises(MissingSelectorsError) as excinfo:
        run_flow(mock_session, _click_flow(), {}, selector_map=selector_map)
    assert excinfo.value.missing == ["ui.x"]
    assert "ui.x" in str(excinfo.value)
