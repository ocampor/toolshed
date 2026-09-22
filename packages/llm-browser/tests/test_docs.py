"""The generated reference is checked against the source, not trusted.

The files themselves are a build artifact, so there is nothing to compare a
committed copy against; what is worth asserting is that the generator runs and
covers every step type.
"""

import pytest
from llm_browser.cli_docs import source_tree
from llm_browser.docgen import DOCUMENTS, reference_documents
from llm_browser.introspect import step_arms

# A whole document has to fit one read by a host that caps its output.
DOC_MAX_CHARS = 20_000


@pytest.fixture(scope="module")
def rendered() -> dict[str, str]:
    source = source_tree()
    assert source is not None, "tests run from a source checkout"
    return reference_documents(source)


def test_the_generator_produces_every_document_it_names(
    rendered: dict[str, str],
) -> None:
    assert set(rendered) == set(DOCUMENTS)
    assert all(text.strip() for text in rendered.values())


@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_every_document_fits_one_read(rendered: dict[str, str], name: str) -> None:
    assert len(rendered[name]) <= DOC_MAX_CHARS


def test_every_step_type_reaches_the_reference(rendered: dict[str, str]) -> None:
    """`docgen` finds step models by name; this is what fails if that rule
    stops matching one."""
    steps = rendered["reference/steps"]
    missing = [
        step_class.__name__
        for _, step_class in step_arms()
        if f"`{step_class.__name__}`" not in steps
    ]
    assert missing == []
