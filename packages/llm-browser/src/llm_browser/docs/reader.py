"""Reading the docs the wheel ships, by name and by section.

Two kinds live side by side: ``reference/*`` is generated from the models by
:mod:`llm_browser.docgen`, ``guide/*`` is hand-written prose. A host serving
these to a model wants one section at a time, so the split lives here rather
than in every caller.
"""

import re
from importlib.resources import files

from pydantic import BaseModel

DOC_ROOT = files("llm_browser") / "docs"

KINDS = ("reference", "guide")

# A doc name, not a path: no traversal, no extension, no nesting below the kind.
NAME = re.compile(rf"^({'|'.join(KINDS)})/[a-z0-9_-]+$")

HEADING = re.compile(r"^#{1,3} +(.+?)\s*$")

FENCE = re.compile(r"^\s*(```|~~~)")


class Section(BaseModel):
    """One heading's worth of a document, the heading line included."""

    heading: str
    text: str


class DocEntry(BaseModel):
    name: str
    title: str
    kind: str
    chars: int


def doc_names() -> list[str]:
    return sorted(
        f"{kind}/{entry.name.removesuffix('.md')}"
        for kind in KINDS
        for entry in (DOC_ROOT / kind).iterdir()
        if entry.name.endswith(".md")
    )


def read(name: str) -> str:
    """One document's markdown. An unknown name is a ``ValueError``."""
    if not NAME.match(name) or name not in doc_names():
        raise ValueError(f"no such doc {name!r}; try one of {', '.join(doc_names())}")
    return (DOC_ROOT / f"{name}.md").read_text(encoding="utf-8")


def sections(name: str) -> list[Section]:
    """Split at every `#`–`###` heading, fenced code kept inside its section.

    A heading inside a fence is sample markdown, not a heading of this
    document, so the fence state decides.
    """
    heading = ""
    lines: list[str] = []
    found: list[Section] = []
    fenced = False
    for line in read(name).splitlines(keepends=True):
        if FENCE.match(line):
            fenced = not fenced
        match = None if fenced else HEADING.match(line)
        if match is None:
            lines.append(line)
            continue
        found.append(Section(heading=heading, text="".join(lines)))
        heading, lines = match.group(1), [line]
    found.append(Section(heading=heading, text="".join(lines)))
    return [section for section in found if section.text.strip()]


def title_of(text: str) -> str:
    for line in text.splitlines():
        match = HEADING.match(line)
        if match:
            return match.group(1)
    return ""


def index() -> list[DocEntry]:
    """Every shipped document, with the title and size a caller picks by."""
    entries = []
    for name in doc_names():
        text = read(name)
        kind, _, stem = name.partition("/")
        entries.append(
            DocEntry(
                name=name,
                title=title_of(text) or stem,
                kind=kind,
                chars=len(text),
            )
        )
    return entries
