"""Serving the shipped docs: by name, by section, and by index."""

import pytest
from llm_browser import docs
from llm_browser.docgen import DOCUMENTS


def test_the_index_lists_every_shipped_file() -> None:
    names = {entry.name for entry in docs.index()}
    assert set(DOCUMENTS) <= names
    assert "guide/flows" in names
    assert all(entry.chars > 0 and entry.title for entry in docs.index())


def test_a_kind_is_read_off_the_name() -> None:
    kinds = {entry.name: entry.kind for entry in docs.index()}
    assert kinds["reference/steps"] == "reference"
    assert kinds["guide/patterns"] == "guide"


@pytest.mark.parametrize(
    "name", ["../models", "guide/../../models", "guide/flows.md", "nope/flows", "flows"]
)
def test_a_name_that_is_a_path_is_refused(name: str) -> None:
    with pytest.raises(ValueError):
        docs.read(name)


def test_sections_split_at_headings_and_keep_their_own_heading() -> None:
    sections = docs.sections("reference/steps")
    headings = [section.heading for section in sections]
    assert "`click`" in headings
    clicked = next(s for s in sections if s.heading == "`click`")
    assert clicked.text.startswith("## `click`")
    assert "dispatch" in clicked.text


def test_a_heading_inside_a_fence_is_not_a_section() -> None:
    """`# parent.yaml` in a YAML example would otherwise split the document."""
    headings = [section.heading for section in docs.sections("guide/flows")]
    assert "parent.yaml" not in headings
    assert "Composition" in headings


def test_every_section_of_a_document_adds_back_up_to_it() -> None:
    joined = "".join(section.text for section in docs.sections("guide/patterns"))
    assert joined == docs.read("guide/patterns")
