"""The generated reference is checked against the source, not trusted.

The files themselves are a build artifact, so there is nothing to compare a
committed copy against; what is worth asserting is that the generator runs and
covers every step type.
"""

import ast
import importlib
from pathlib import Path

import llm_browser
import pytest
from llm_browser.cli_docs import source_tree
from llm_browser.docgen import (
    DOCUMENTS,
    covered_modules,
    load_package,
    reference_documents,
)
from llm_browser.introspect import step_arms
from pydantic import BaseModel

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


# Prose that explains the library to its user has to reach a shipped doc.
# These are the modules whose long docstring is addressed to a maintainer
# instead, so nothing renders them.
MAINTAINER_MODULES = {
    "llm_browser.docgen",
    "llm_browser.docs.reader",
    "llm_browser.introspect",
    "llm_browser.session_input",
    "llm_browser.state",
}

# Shorter than this and a module docstring is a label, not documentation.
PROSE_LINES = 5

MODEL_MODULES = ("models", "repeat", "selectors", "behavior", "results")


def documented_modules() -> set[str]:
    source = source_tree()
    assert source is not None
    return covered_modules(load_package(source))


def module_prose() -> dict[str, int]:
    """Every module under `src/llm_browser`, by the length of its docstring."""
    root = Path("src/llm_browser").resolve()
    if not root.is_dir():
        root = Path(llm_browser.__file__).resolve().parent
    found = {}
    for path in sorted(root.rglob("*.py")):
        docstring = ast.get_docstring(ast.parse(path.read_text())) or ""
        dotted = ".".join(
            ("llm_browser", *path.relative_to(root).with_suffix("").parts)
        )
        found[dotted.removesuffix(".__init__")] = len(docstring.splitlines())
    return found


def test_every_module_that_explains_itself_reaches_a_doc() -> None:
    """A guide folded into a module docstring and never added to `DOCUMENTS`
    is a topic that lost its documentation — which is how `repeat`, `cli` and
    `drivers` went missing."""
    documented = documented_modules()
    unreachable = sorted(
        name
        for name, lines in module_prose().items()
        if lines > PROSE_LINES
        and name not in documented
        and name not in MAINTAINER_MODULES
    )
    assert unreachable == []


def public_models() -> list[str]:
    modules = (importlib.import_module(f"llm_browser.{n}") for n in MODEL_MODULES)
    return [
        f"{module.__name__}.{name}"
        for module in modules
        for name, member in vars(module).items()
        if not name.startswith("_")
        and isinstance(member, type)
        and issubclass(member, BaseModel)
        and member.__module__ == module.__name__
    ]


def test_every_public_model_is_rendered_somewhere(rendered: dict[str, str]) -> None:
    documents = "\n".join(rendered.values())
    missing = [
        path
        for path in public_models()
        if f"## `{path.rsplit('.', 1)[1]}`" not in documents
    ]
    assert missing == []
