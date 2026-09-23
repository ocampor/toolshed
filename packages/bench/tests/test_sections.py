from bench.docs.sections import Section, sections_of

TEXT = """Preamble.

# Title

## Example

```markdown
# not a heading
```

### Empty
"""


def test_sections_of_keeps_fenced_headings_inside_their_section() -> None:
    assert sections_of(TEXT) == [
        Section("", "Preamble.\n\n"),
        Section("Title", "# Title\n\n"),
        Section("Example", "## Example\n\n```markdown\n# not a heading\n```\n\n"),
        Section("Empty", "### Empty\n"),
    ]
