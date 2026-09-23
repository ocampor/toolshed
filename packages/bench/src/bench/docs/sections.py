"""Stdlib only, so splitting text needs no ``docs`` extra."""

import re
from typing import NamedTuple

HEADING = re.compile(r"^#{1,3} +(.+?)\s*$")

FENCE = re.compile(r"^\s*(```|~~~)")


class Section(NamedTuple):
    """One heading's worth of a document, the heading line included."""

    heading: str
    text: str


def sections_of(text: str) -> list[Section]:
    """Split at every `#`–`###` heading, fenced code kept inside its section.

    A heading inside a fence is sample markdown, not a heading of this
    document, so the fence state decides.
    """
    heading = ""
    lines: list[str] = []
    found: list[Section] = []
    fenced = False
    for line in text.splitlines(keepends=True):
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
