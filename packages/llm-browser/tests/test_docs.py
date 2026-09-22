"""The shipped docs are checked against the models, not trusted.

A generated file is only worth shipping if something fails when the code moves
under it, and only useful to a reader that can fetch one section at a time.
"""

import pytest
from llm_browser.docgen import DOCUMENTS, docs_dir, reference_documents
from llm_browser.introspect import own_fields, step_arms

# A whole document has to fit one read by a host that caps its output.
DOC_MAX_CHARS = 20_000


@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_the_shipped_reference_matches_the_models(name: str) -> None:
    path = docs_dir() / f"{name}.md"
    assert path.read_text() == reference_documents()[name], (
        f"{name}.md is stale; regenerate with `uv run llm-browser docs --write`"
    )


@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_every_document_fits_one_read(name: str) -> None:
    assert len(reference_documents()[name]) <= DOC_MAX_CHARS


def test_no_step_field_is_left_out_of_the_reference() -> None:
    """The step sections drop the targeting fields into one shared table, so
    the count has to be checked against the models rather than assumed."""
    steps = reference_documents()["reference/steps"]
    missing = [
        f"{action}.{field}"
        for action, step_class in step_arms()
        for field in own_fields(step_class)
        if f"| `{field}` |" not in steps
    ]
    assert missing == []
