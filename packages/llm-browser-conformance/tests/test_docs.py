"""The docs are checked, not trusted.

``xpass`` catches a gap that closes; nothing catches a table row whose
wording drifted, a row deleted from the code, or a new gap nobody wrote down.
"""

from pathlib import Path

from llm_browser_conformance.gaps import known_gaps_document

PACKAGE_DIR = Path(__file__).resolve().parent.parent
README = PACKAGE_DIR / "README.md"
KNOWN_GAPS = PACKAGE_DIR / "docs" / "known-gaps.md"

README_MAX_LINES = 200


def test_the_known_gaps_table_matches_the_scenarios() -> None:
    assert KNOWN_GAPS.read_text() == known_gaps_document(), (
        "docs/known-gaps.md is stale; regenerate with "
        "`uv run llm-browser-check --gaps > docs/known-gaps.md`"
    )


def test_the_readme_stays_a_readme() -> None:
    lines = README.read_text().splitlines()
    assert len(lines) <= README_MAX_LINES, f"README is {len(lines)} lines"
