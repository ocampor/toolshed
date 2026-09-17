"""Tests for the in-page JavaScript loaded from ``js/``."""

import json
import shutil
import subprocess
from pathlib import Path

import patchright
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
    survey_js,
    viewport_fit_js,
)

# These scripts run in a browser, but a plain JS runtime proves their
# semantics — and patchright ships the node its own driver runs on, so they
# run wherever the package is installed, CI included.
JS_RUNTIME = shutil.which("node") or str(
    Path(patchright.__file__).parent / "driver" / "node"
)
HAS_JS_RUNTIME = Path(JS_RUNTIME).exists()


def test_extract_rows_js_is_a_rows_spec_function() -> None:
    source = extract_rows_js()
    assert source.startswith("(rows, spec) =>")
    assert "querySelector" in source
    assert "getAttribute" in source


def test_extract_rows_js_reads_the_property_allowlist_from_python() -> None:
    """One list, substituted in, so the page-side rule cannot drift from
    ``Driver.read_field``."""
    assert json.dumps(list(EXTRACT_PROPERTIES)) in extract_rows_js()


def test_load_script_is_cached_and_reads_from_js_dir() -> None:
    assert (JS_DIR / "extract_rows.js").is_file()
    assert load_script("extract_rows") is load_script("extract_rows")


def test_load_script_missing_file() -> None:
    with pytest.raises(FileNotFoundError):
        load_script("no_such_script")


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
console.log(JSON.stringify(EXTRACT([row], spec)));
"""


@pytest.mark.skipif(not HAS_JS_RUNTIME, reason="no node binary available")
def test_extract_rows_js_semantics_in_node(tmp_path: Path) -> None:
    """Run the real script over fake elements: property reads, attributes,
    a missing child, and a null child_selector meaning the row itself."""
    script = tmp_path / "harness.mjs"
    script.write_text(
        f"const EXTRACT = {extract_rows_js()};\n{FAKE_DOM_HARNESS}",
    )
    out = subprocess.run(
        [JS_RUNTIME, str(script)], capture_output=True, text=True, check=True
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
        [JS_RUNTIME, str(script)], capture_output=True, text=True, check=True
    )
    return dict(json.loads(out.stdout))


@pytest.mark.skipif(not HAS_JS_RUNTIME, reason="no node binary available")
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


@pytest.mark.skipif(not HAS_JS_RUNTIME, reason="no node binary available")
def test_a_disabled_optgroup_is_its_own_answer(tmp_path: Path) -> None:
    """`parentElement.disabled` blamed the option; an option inside a disabled
    `<optgroup>` has no `disabled` of its own and used to be chosen."""
    result = run_select_harness("g", tmp_path, group_disabled=True)
    assert result == {"outcome": "group-disabled", **UNTOUCHED}


@pytest.mark.skipif(not HAS_JS_RUNTIME, reason="no node binary available")
def test_a_disabled_select_is_its_own_answer(tmp_path: Path) -> None:
    """Not "the option is disabled": the option is fine, the control is not."""
    result = run_select_harness("c", tmp_path, select_disabled=True)
    assert result == {"outcome": "select-disabled", **UNTOUCHED}


@pytest.mark.skipif(not HAS_JS_RUNTIME, reason="no node binary available")
def test_a_label_stands_in_for_the_control_it_labels(tmp_path: Path) -> None:
    """The Playwright family resolves one before acting; rejecting it here
    would make nodriver refuse a target the others accept."""
    label = '{ tagName: "LABEL", control: select }'
    assert run_select_harness("c", tmp_path, target=label) == CHOSE_C


@pytest.mark.skipif(not HAS_JS_RUNTIME, reason="no node binary available")
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


HIT_HARNESS = """
const el = (tag, text, cls) => ({
  tagName: tag,
  innerText: text,
  getAttribute: (name) => (name === "class" ? cls : null),
  contains(node) { return node === this; },
});
const link = el("A", "Salir", "headerlogout");
const span = el("SPAN", "Salir", "label");
const menu = el("LI", "Estados de cuenta", "menu-item");
const page = el("HTML", "", "");
const label = el("LABEL", "Remember me", "field-label");
link.contains = (node) => node === link || node === span;
page.contains = () => true;
label.closest = (sel) => (sel === "label" ? label : null);
label.control = link;
globalThis.document = { elementFromPoint: () => AT };
console.log(JSON.stringify(HIT(link)));
"""


def run_hit_harness(at: str, tmp_path: Path) -> dict[str, object]:
    from llm_browser.scripts import hit_test_js

    script = tmp_path / "harness.mjs"
    script.write_text(
        f"const HIT = {hit_test_js((12.0, 34.0))}\n{HIT_HARNESS.replace('AT', at)}"
    )
    out = subprocess.run(
        [JS_RUNTIME, str(script)], capture_output=True, text=True, check=True
    )
    return dict(json.loads(out.stdout))


TEXT_MATCH_HARNESS = """
// `getClientRects` is what the script asks before reading `innerText`,
// `getComputedStyle` is how it spots a `display:contents` scope, and
// `querySelectorAll` honours the `:not(...)` clauses the way a real one does.
const ELEMENT = 1;
const TEXT = 3;
const words = (data) => ({ nodeType: TEXT, data });
const node = (
  innerText,
  childNodes = [],
  tag = "DIV",
  visible = true,
  display = "block",
) => ({
  nodeType: ELEMENT,
  innerText,
  tagName: tag,
  display,
  childNodes,
  getClientRects: () => (visible ? [{}] : []),
  querySelectorAll: (selector) =>
    childNodes.filter(
      (child) =>
        child.nodeType === ELEMENT &&
        !selector.includes(`:not(${child.tagName.toLowerCase()})`),
    ),
});
globalThis.getComputedStyle = (el) => ({ display: el.display });
const toast = node("Sesión  finalizada\\n");
// Not rendered, and neither is what it holds: `innerText` falls back to the
// subtree's `textContent`, which is the trap.
const buried = node("Sesión  finalizada\\n", [
  node("Sesión  finalizada", [], "DIV", false),
], "DIV", false, "none");
// `display:contents`: no box of its own, children laid out as usual.
const wrapper = node("Sesión  finalizada", [
  node("Sesión  finalizada\\n"),
], "DIV", false, "contents");
// The same, holding the text itself rather than an element that does.
const bare = node("Sesión  finalizada", [
  words("Sesión  finalizada\\n"),
], "DIV", false, "contents");
const scripted = node("", [node("Sesión  finalizada", [], "SCRIPT")]);
globalThis.document = { body: node("Menú\\n  Sesión  finalizada\\n", [toast]) };
console.log(JSON.stringify({
  page: MATCH(),
  scoped: MATCH(toast),
  hidden: MATCH(buried),
  contents: MATCH(wrapper),
  bare: MATCH(bare),
  scripted: MATCH(scripted),
  elsewhere: MATCH(node("Cargando")),
}));
"""


def test_text_match_js_does_not_substitute_the_text_it_carries() -> None:
    """The waited-for text is a value, not source: a page that says a
    placeholder's name must not rewrite the script that looks for it."""
    from llm_browser.scripts import text_match_js

    source = text_match_js(constants.TEXT_MATCH_EXACT_PLACEHOLDER, exact=True)

    assert json.dumps(constants.TEXT_MATCH_EXACT_PLACEHOLDER) in source
    assert "const exact = true;" in source


def run_text_match(text: str, exact: bool, tmp_path: Path) -> dict[str, bool]:
    from llm_browser.scripts import text_match_js

    script = tmp_path / "harness.mjs"
    script.write_text(
        f"const MATCH = {text_match_js(text, exact)}\n{TEXT_MATCH_HARNESS}"
    )
    out = subprocess.run(
        [JS_RUNTIME, str(script)], capture_output=True, text=True, check=True
    )
    return dict(json.loads(out.stdout))


@pytest.mark.skipif(not HAS_JS_RUNTIME, reason="no node binary available")
@pytest.mark.parametrize(
    ("at", "expected"),
    [
        ("link", {"target": True, "tag": "a", "class_name": "headerlogout"}),
        # The hit lands on the innermost node, so the span inside the link is
        # the link: a descendant is never a cover.
        ("span", {"target": True, "tag": "span", "class_name": "label"}),
        ("menu", {"target": False, "tag": "li", "class_name": "menu-item"}),
        # An ancestor under the pointer means the point fell in a gap in the
        # target's own box — the press would go to the ancestor.
        ("page", {"target": False, "tag": "html", "class_name": ""}),
        ("label", {"target": True, "tag": "label", "class_name": "field-label"}),
        ("null", {"target": True, "tag": None, "class_name": None}),
    ],
)
def test_hit_test_js_says_what_the_point_is_over(
    at: str, expected: dict[str, object], tmp_path: Path
) -> None:
    read = run_hit_harness(at, tmp_path)
    hit = read["hit"] or {}

    assert {
        "target": read["target"],
        "tag": hit.get("tag"),  # type: ignore[union-attr]
        "class_name": hit.get("class_name"),  # type: ignore[union-attr]
    } == expected


VIEWPORT_FIT_HARNESS = """
globalThis.innerWidth = INNER_WIDTH;
globalThis.innerHeight = INNER_HEIGHT;
globalThis.scrollY = SCROLL_Y;
const el = { getBoundingClientRect: () => (BOX) };
console.log(JSON.stringify(FIT(el)));
"""

INNER_WIDTH = 1200
INNER_HEIGHT = 800
SCROLL_Y = 250.4


def run_viewport_fit_harness(
    box: dict[str, float], tmp_path: Path
) -> dict[str, object]:
    body = (
        VIEWPORT_FIT_HARNESS.replace("INNER_WIDTH", str(INNER_WIDTH))
        .replace("INNER_HEIGHT", str(INNER_HEIGHT))
        .replace("SCROLL_Y", str(SCROLL_Y))
        .replace("BOX", json.dumps(box))
    )
    script = tmp_path / "harness.mjs"
    script.write_text(f"const FIT = {viewport_fit_js()}\n{body}")
    out = subprocess.run(
        [JS_RUNTIME, str(script)], capture_output=True, text=True, check=True
    )
    return dict(json.loads(out.stdout))


@pytest.mark.skipif(not HAS_JS_RUNTIME, reason="no node binary available")
@pytest.mark.parametrize(
    ("rect", "expected_gap"),
    [
        # Below the fold: gap is the box's centre minus the viewport's centre.
        pytest.param({"top": 900, "height": 100, "bottom": 1000}, 550, id="below_fold"),
        # Above the fold: same formula, negative.
        pytest.param(
            {"top": -300, "height": 100, "bottom": -200}, -650, id="above_fold"
        ),
        # Fully in view and clear of both 15% dead zones: left alone.
        pytest.param(
            {"top": 300, "height": 100, "bottom": 400}, 0, id="clear_of_dead_zones"
        ),
        # In view but under a fixed nav band inside the top dead zone: the old
        # minimal-gap rule saw the box in the viewport and returned 0 here.
        pytest.param(
            {"top": 50, "height": 50, "bottom": 100}, -325, id="top_dead_zone"
        ),
        # Taller than the viewport: brought to its top edge, not centred.
        pytest.param(
            {"top": 200, "height": 900, "bottom": 1100},
            200,
            id="taller_than_viewport",
        ),
    ],
)
def test_viewport_fit_js_aims_the_box_at_the_middle(
    rect: dict[str, float], expected_gap: int, tmp_path: Path
) -> None:
    read = run_viewport_fit_harness(rect, tmp_path)

    assert read["gap"] == expected_gap
    assert read["centre"] == [INNER_WIDTH / 2, INNER_HEIGHT / 2]
    assert read["scrollY"] == round(SCROLL_Y)


@pytest.mark.skipif(not HAS_JS_RUNTIME, reason="no node binary available")
@pytest.mark.parametrize(
    ("text", "exact", "expected"),
    [
        # Newlines and the `&nbsp;` an XPath `contains(text(), ...)` trips over
        # both normalise away. `hidden` and `scripted` hold the text but are
        # never rendered, so no mode may see it; `contents` and `bare` render
        # no box of their own yet lay out what they hold — a child element, a
        # text node — as usual, so every mode must see it.
        (
            "Sesión finalizada",
            False,
            {
                "page": True,
                "scoped": True,
                "hidden": False,
                "contents": True,
                "bare": True,
                "scripted": False,
                "elsewhere": False,
            },
        ),
        (
            "finalizada",
            False,
            {
                "page": True,
                "scoped": True,
                "hidden": False,
                "contents": True,
                "bare": True,
                "scripted": False,
                "elsewhere": False,
            },
        ),
        # Exact: the toast's own text, which the page holds only as a subtree.
        (
            "Sesión finalizada",
            True,
            {
                "page": True,
                "scoped": True,
                "hidden": False,
                "contents": True,
                "bare": True,
                "scripted": False,
                "elsewhere": False,
            },
        ),
        (
            "finalizada",
            True,
            {
                "page": False,
                "scoped": False,
                "hidden": False,
                "contents": False,
                "bare": False,
                "scripted": False,
                "elsewhere": False,
            },
        ),
    ],
)
def test_text_match_js_reads_normalised_rendered_text(
    text: str, exact: bool, expected: dict[str, bool], tmp_path: Path
) -> None:
    assert run_text_match(text, exact, tmp_path) == expected
