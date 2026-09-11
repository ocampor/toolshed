"""Tests for the in-page JavaScript loaded from ``js/``."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from llm_browser.scripts import JS_DIR, extract_rows_js, load_script


def test_extract_rows_js_is_a_rows_spec_function() -> None:
    source = extract_rows_js()
    assert source.startswith("(rows, spec) =>")
    assert "querySelector" in source
    assert "getAttribute" in source


@pytest.mark.parametrize("attribute", ["textContent", "value"])
def test_extract_rows_js_handles_property_reads(attribute: str) -> None:
    assert f'attribute === "{attribute}"' in extract_rows_js()


def test_load_script_is_cached_and_reads_from_js_dir() -> None:
    assert (JS_DIR / "extract_rows.js").is_file()
    assert load_script("extract_rows") is extract_rows_js()


def test_load_script_missing_file() -> None:
    with pytest.raises(FileNotFoundError):
        load_script("no_such_script")


FAKE_DOM_HARNESS = """
const makeEl = (attrs, text, value) => ({
  textContent: text,
  value,
  getAttribute: (name) => (name in attrs ? attrs[name] : null),
});
const child = makeEl({ href: "/a" }, "Alice", "typed");
const row = { querySelector: (sel) => (sel === "td.name" ? child : null) };
const spec = {
  name: { child_selector: "td.name", attribute: "textContent" },
  url: { child_selector: "td.name", attribute: "href" },
  typed: { child_selector: "td.name", attribute: "value" },
  missing: { child_selector: "td.nope", attribute: "textContent" },
  self: { child_selector: null, attribute: "textContent" },
};
row.textContent = "whole row";
console.log(JSON.stringify(EXTRACT([row], spec)));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_extract_rows_js_semantics_in_node(tmp_path: Path) -> None:
    """Run the real script over fake elements: property reads, attributes,
    a missing child, and a null child_selector meaning the row itself."""
    script = tmp_path / "harness.mjs"
    script.write_text(
        f"const EXTRACT = {extract_rows_js()};\n{FAKE_DOM_HARNESS}",
    )
    out = subprocess.run(
        ["node", str(script)], capture_output=True, text=True, check=True
    )
    assert json.loads(out.stdout) == [
        {
            "name": "Alice",
            "url": "/a",
            "typed": "typed",
            "missing": None,
            "self": "whole row",
        }
    ]


SELECT_HARNESS = """
const group = { tagName: "OPTGROUP", disabled: GROUP_DISABLED };
const makeOption = (value, label, index, disabled, inGroup) => ({
  value, label, index, disabled,
  text: " " + label + " ",
  closest: (sel) => (sel === "optgroup" && inGroup ? group : null),
});
const options = [
  makeOption("a", "Alpha", 0, false, false),
  makeOption("b", "Bravo", 1, true, false),
  makeOption("c", "Charlie", 2, false, false),
  makeOption("g", "Golf", 3, false, true),
];
const select = {
  tagName: "SELECT",
  disabled: SELECT_DISABLED,
  options,
  selectedIndex: 0,
  events: [],
  dispatchEvent(event) { this.events.push(event.type); return true; },
};
const target = TARGET;
console.log(JSON.stringify({
  outcome: SELECT(target),
  selectedIndex: select.selectedIndex,
  events: select.events,
}));
"""

CHOSE_C = {"outcome": "ok", "selectedIndex": 2, "events": ["input", "change"]}
UNTOUCHED = {"selectedIndex": 0, "events": []}


def run_select_harness(
    value: str,
    tmp_path: Path,
    *,
    target: str = "select",
    select_disabled: bool = False,
    group_disabled: bool = False,
) -> dict[str, object]:
    from llm_browser.scripts import select_option_js

    body = (
        SELECT_HARNESS.replace("SELECT_DISABLED", str(select_disabled).lower())
        .replace("GROUP_DISABLED", str(group_disabled).lower())
        .replace("TARGET", target)
    )
    script = tmp_path / "harness.mjs"
    script.write_text(
        "class Event { constructor(type) { this.type = type; } }\n"
        f"const SELECT = {select_option_js(value)};\n{body}"
    )
    out = subprocess.run(
        ["node", str(script)], capture_output=True, text=True, check=True
    )
    return dict(json.loads(out.stdout))


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("c", CHOSE_C),
        # Playwright's select_option matches the value or the label, so a flow
        # written against the text a person reads works on every driver.
        ("Charlie", CHOSE_C),
        ("b", {"outcome": "option-disabled", **UNTOUCHED}),
        ("z", {"outcome": "missing", **UNTOUCHED}),
    ],
)
def test_select_option_js_picks_or_says_why_not(
    value: str, expected: dict[str, object], tmp_path: Path
) -> None:
    assert run_select_harness(value, tmp_path) == expected


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_a_disabled_optgroup_is_its_own_answer(tmp_path: Path) -> None:
    """`parentElement.disabled` blamed the option; an option inside a disabled
    `<optgroup>` has no `disabled` of its own and used to be chosen."""
    result = run_select_harness("g", tmp_path, group_disabled=True)
    assert result == {"outcome": "group-disabled", **UNTOUCHED}


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_a_disabled_select_is_its_own_answer(tmp_path: Path) -> None:
    """Not "the option is disabled": the option is fine, the control is not."""
    result = run_select_harness("c", tmp_path, select_disabled=True)
    assert result == {"outcome": "select-disabled", **UNTOUCHED}


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_a_label_stands_in_for_the_control_it_labels(tmp_path: Path) -> None:
    """The Playwright family resolves one before acting; rejecting it here
    would make nodriver refuse a target the others accept."""
    label = '{ tagName: "LABEL", control: select }'
    assert run_select_harness("c", tmp_path, target=label) == CHOSE_C


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_anything_else_is_not_a_select(tmp_path: Path) -> None:
    assert run_select_harness("c", tmp_path, target='{ tagName: "DIV" }') == {
        "outcome": "not-a-select",
        **UNTOUCHED,
    }


def test_the_control_tag_script_resolves_a_label() -> None:
    from llm_browser.scripts import select_control_tag_js

    source = select_control_tag_js()
    assert 'el.tagName === "LABEL"' in source
    assert "el.control" in source
