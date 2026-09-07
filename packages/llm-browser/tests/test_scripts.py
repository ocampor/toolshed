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
