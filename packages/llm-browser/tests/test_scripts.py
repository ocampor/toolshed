"""Tests for the in-page JavaScript loaded from ``js/``."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from llm_browser import constants
from llm_browser.constants import EXTRACT_PROPERTIES
from llm_browser.parse import ExtractField, row_spec
from llm_browser.scripts import (
    JS_DIR,
    count_selectors_js,
    explore_first_js,
    explore_many_js,
    extract_rows_js,
    load_script,
    read_property_js,
    survey_js,
)


def test_extract_rows_js_is_a_rows_spec_function() -> None:
    source = extract_rows_js()
    assert source.startswith("(rows, { spec, exclude }) =>")
    assert "querySelector" in source
    assert "getAttribute" in source


def test_extract_rows_js_reads_the_property_allowlist_from_python() -> None:
    """One list, substituted in, so the page-side rule cannot drift from
    ``Driver.read_field``."""
    assert json.dumps(list(EXTRACT_PROPERTIES)) in extract_rows_js()


def test_read_property_js_prunes_only_when_asked() -> None:
    """The per-element path mirrors `js/extract_rows.js`: one selector list,
    pruned off a copy, and nothing at all to do when `exclude` is empty."""
    assert read_property_js("textContent") == "(el) => el.textContent"
    with_exclude = read_property_js("textContent", ["span.badge", ".sr-only"])
    assert 'querySelectorAll("span.badge, .sr-only")' in with_exclude
    assert "cloneNode(true)" in with_exclude
    assert with_exclude.endswith("return copy.textContent; }")


def test_load_script_is_cached_and_reads_from_js_dir() -> None:
    assert (JS_DIR / "extract_rows.js").is_file()
    assert load_script("extract_rows") is load_script("extract_rows")


def test_load_script_missing_file() -> None:
    with pytest.raises(FileNotFoundError):
        load_script("no_such_script")


JS_RUNTIME = shutil.which("node") or shutil.which("bun")


FAKE_DOM_HARNESS = """
const makeEl = (attrs, text, value) => ({
  textContent: text,
  innerText: text.trim(),
  value,
  tagName: "TD",
  childElementCount: 2,
  getAttribute: (name) => (name in attrs ? attrs[name] : null),
});
const child = makeEl({ href: "/a" }, "Alice", "typed");
const row = { querySelector: (sel) => (sel === "td.name" ? child : null) };
const spec = {
  name: { child_selector: "td.name", attribute: "textContent" },
  url: { child_selector: "td.name", attribute: "href" },
  typed: { child_selector: "td.name", attribute: "value" },
  rendered: { child_selector: "td.name", attribute: "innerText" },
  tag: { child_selector: "td.name", attribute: "tagName" },
  kids: { child_selector: "td.name", attribute: "childElementCount" },
  gone: { child_selector: "td.name", attribute: "data-nope" },
  missing: { child_selector: "td.nope", attribute: "textContent" },
  self: { child_selector: null, attribute: "textContent" },
};
row.textContent = "whole row";
console.log(JSON.stringify(EXTRACT([row], { spec, exclude: [] })));
"""


@pytest.mark.skipif(JS_RUNTIME is None, reason="no JS runtime installed")
def test_extract_rows_js_semantics_in_node(tmp_path: Path) -> None:
    """Run the real script over fake elements: property reads, attributes,
    a missing child, and a null child_selector meaning the row itself."""
    script = tmp_path / "harness.mjs"
    script.write_text(
        f"const EXTRACT = {extract_rows_js()};\n{FAKE_DOM_HARNESS}",
    )
    out = subprocess.run(
        [str(JS_RUNTIME), str(script)], capture_output=True, text=True, check=True
    )
    assert json.loads(out.stdout) == [
        {
            "name": "Alice",
            "url": "/a",
            "typed": "typed",
            "rendered": "Alice",
            "tag": "TD",
            "kids": "2",
            "gone": None,
            "missing": None,
            "self": "whole row",
        }
    ]


EXCLUDE_HARNESS = """
class Node {
  constructor(sel, text, children) {
    this.sel = sel;
    this.text = text || "";
    this.children = children || [];
    this.children.forEach((child) => (child.parent = this));
  }
  get textContent() {
    if (!this.children.length) return this.text;
    return this.children.map((child) => child.textContent).join("");
  }
  cloneNode() {
    return new Node(this.sel, this.text, this.children.map((c) => c.cloneNode()));
  }
  querySelectorAll(selector) {
    const wanted = selector.split(", ");
    const found = [];
    const walk = (node) =>
      node.children.forEach((child) => {
        if (wanted.includes(child.sel)) found.push(child);
        walk(child);
      });
    walk(this);
    return found;
  }
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }
  remove() {
    this.parent.children = this.parent.children.filter((c) => c !== this);
  }
  getAttribute() {
    return null;
  }
}
const spec = { text: { child_selector: null, attribute: "textContent" } };
const row = () =>
  new Node("tr", "", [
    new Node("td.title", "Widget"),
    new Node("span.badge", " 5 reviews"),
  ]);
console.log(
  JSON.stringify({
    excluded: EXTRACT([row()], { spec, exclude: EXCLUDE_JSON }),
    kept: EXTRACT([row()], { spec, exclude: [] }),
  })
);
"""


def run_exclude_harness(exclude: list[str], tmp_path: Path) -> dict[str, object]:
    script = tmp_path / "exclude.mjs"
    script.write_text(
        f"const EXTRACT = {extract_rows_js()};\n"
        + EXCLUDE_HARNESS.replace("EXCLUDE_JSON", json.dumps(exclude))
    )
    out = subprocess.run(
        [str(JS_RUNTIME), str(script)], capture_output=True, text=True, check=True
    )
    return dict(json.loads(out.stdout))


@pytest.mark.skipif(JS_RUNTIME is None, reason="no JS runtime installed")
def test_read_exclude_drops_subtree_text(tmp_path: Path) -> None:
    result = run_exclude_harness(["span.badge"], tmp_path)
    assert result["excluded"] == [{"text": "Widget"}]
    assert result["kept"] == [{"text": "Widget 5 reviews"}]


@pytest.mark.skipif(JS_RUNTIME is None, reason="no JS runtime installed")
def test_read_exclude_no_match_is_noop(tmp_path: Path) -> None:
    result = run_exclude_harness(["span.nothing-here"], tmp_path)
    assert result["excluded"] == result["kept"] == [{"text": "Widget 5 reviews"}]


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
        [str(JS_RUNTIME), str(script)], capture_output=True, text=True, check=True
    )
    return dict(json.loads(out.stdout))


@pytest.mark.skipif(JS_RUNTIME is None, reason="no JS runtime installed")
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


@pytest.mark.skipif(JS_RUNTIME is None, reason="no JS runtime installed")
def test_a_disabled_optgroup_is_its_own_answer(tmp_path: Path) -> None:
    """`parentElement.disabled` blamed the option; an option inside a disabled
    `<optgroup>` has no `disabled` of its own and used to be chosen."""
    result = run_select_harness("g", tmp_path, group_disabled=True)
    assert result == {"outcome": "group-disabled", **UNTOUCHED}


@pytest.mark.skipif(JS_RUNTIME is None, reason="no JS runtime installed")
def test_a_disabled_select_is_its_own_answer(tmp_path: Path) -> None:
    """Not "the option is disabled": the option is fine, the control is not."""
    result = run_select_harness("c", tmp_path, select_disabled=True)
    assert result == {"outcome": "select-disabled", **UNTOUCHED}


@pytest.mark.skipif(JS_RUNTIME is None, reason="no JS runtime installed")
def test_a_label_stands_in_for_the_control_it_labels(tmp_path: Path) -> None:
    """The Playwright family resolves one before acting; rejecting it here
    would make nodriver refuse a target the others accept."""
    label = '{ tagName: "LABEL", control: select }'
    assert run_select_harness("c", tmp_path, target=label) == CHOSE_C


@pytest.mark.skipif(JS_RUNTIME is None, reason="no JS runtime installed")
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


def test_explore_first_js_is_an_async_element_function() -> None:
    """It has to be async: `stable` is two rects a beat apart, in one call."""
    source = explore_first_js()
    assert source.startswith("async (el) =>")
    assert constants.EXPLORE_LIMITS_PLACEHOLDER not in source


def test_explore_first_js_reads_every_limit_from_python() -> None:
    """One source for the limits, so the page side and `FirstMatch` cannot
    disagree about what counts as interactive or how long "still" is."""
    source = explore_first_js()
    assert f'"stable_delay_ms": {constants.EXPLORE_STABLE_DELAY_MS}' in source
    assert f'"text_max": {constants.EXPLORE_TEXT_MAX_CHARS}' in source
    assert f'"cover_text_max": {constants.EXPLORE_COVER_TEXT_MAX_CHARS}' in source
    assert json.dumps(list(constants.INTERACTIVE_TAGS)) in source
    assert json.dumps(list(constants.INTERACTIVE_ROLES)) in source
    assert json.dumps(list(constants.TESTID_ATTRIBUTES)) in source
    assert f'"nested_text_max": {constants.EXPLORE_NESTED_TEXT_MAX_CHARS}' in source
    assert f'"ancestor_levels": {constants.EXPLORE_ANCESTOR_LEVELS}' in source


def test_the_element_read_is_shared_rather_than_copied() -> None:
    """`explore` and `explore_many` answer the same questions about an
    element, so one script answers them."""
    element = load_script("explore_element")
    assert element.lstrip().startswith("//")
    assert "async (el, limits) =>" in element

    batch = explore_many_js([{"selector": ".row", "extract": {}}], 3, 200, 3000)
    assert element.splitlines()[-1] in batch
    for source in (explore_first_js(), batch):
        assert constants.EXPLORE_ELEMENT_PLACEHOLDER not in source
        assert constants.EXPLORE_LIMITS_PLACEHOLDER not in source


def test_explore_many_js_carries_the_batch_it_was_asked_for() -> None:
    """The targets, the sample size and the wait are the page's to apply:
    everything the batch needs goes over in the one call."""
    source = explore_many_js(
        [{"selector": ".row", "extract": {"title": {"child_selector": "a"}}}],
        2,
        120,
        1500,
    )

    assert source.lstrip().startswith("//")
    assert '"selector": ".row"' in source
    assert '"child_selector": "a"' in source
    assert '"sample": 2' in source
    assert '"timeout_ms": 1500' in source
    assert f'"poll_ms": {constants.EXPLORE_MANY_POLL_MS}' in source
    assert json.dumps(list(constants.EXTRACT_PROPERTIES)) in source
    assert constants.EXPLORE_BATCH_PLACEHOLDER not in source


@pytest.mark.parametrize("spec", ["@innerText", "@outerHTML"])
def test_explore_reads_a_property_spec_off_the_element(spec: str) -> None:
    """`@innerText` and `@outerHTML` are DOM properties, not attributes: the
    batch carries the same allowlist the page-side read branches on."""
    field = ExtractField.parse(spec)
    assert field.attribute in EXTRACT_PROPERTIES

    source = explore_many_js(
        [{"selector": ".row", "extract": dict(row_spec({"v": field}))}], 1, 50, 500
    )
    assert f'"attribute": "{field.attribute}"' in source
    assert "batch.properties.includes(field.attribute)" in source


def test_survey_js_reads_every_cap_from_python() -> None:
    source = survey_js()

    assert f'"max_raw_landmarks": {constants.SURVEY_MAX_RAW_LANDMARKS}' in source
    assert f'"max_hrefs": {constants.SURVEY_MAX_HREFS}' in source
    assert f'"min_siblings": {constants.SURVEY_MIN_SIBLINGS}' in source
    assert json.dumps(list(constants.TESTID_ATTRIBUTES)) in source
    assert constants.SURVEY_LIMITS_PLACEHOLDER not in source
    # A survey never acts on the page: it is the read an author starts with.
    assert "click(" not in source and "scrollIntoView" not in source


def test_the_counting_script_asks_about_the_selectors_it_was_given() -> None:
    """The selectors are built in Python, so the page is asked about them
    rather than re-deriving them — one `querySelectorAll` each."""
    source = count_selectors_js(["article.dense", '[aria-label="Next"]'])

    assert json.dumps(["article.dense", '[aria-label="Next"]']) in source
    assert "doc.querySelectorAll(selector).length" in source
    assert constants.SURVEY_COUNT_PLACEHOLDER not in source
