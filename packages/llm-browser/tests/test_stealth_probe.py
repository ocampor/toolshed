"""Tests for the stealth probe's match-text builder."""

import pytest

from scripts.stealth_probe import page_text


@pytest.mark.parametrize(
    ("title", "body", "expected"),
    [
        ("Just a moment...", "", "Just a moment..."),
        ("Just a moment...", None, "Just a moment..."),
        ("", "You are a bot", "You are a bot"),
        (None, "You are a bot", "You are a bot"),
        ("Title", "Body", "Title\nBody"),
        (None, None, ""),
    ],
)
def test_page_text_joins_present_parts(
    title: str | None, body: str | None, expected: str
) -> None:
    assert page_text(title, body) == expected
