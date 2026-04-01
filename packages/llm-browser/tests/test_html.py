"""Tests for HTML cleaning utilities."""

from llm_browser.html import clean_html


def test_strips_script_tags() -> None:
    html = "<div><script>alert('x')</script><p>Hello</p></div>"
    result = clean_html(html)
    assert "<script>" not in result
    assert "Hello" in result


def test_strips_style_tags() -> None:
    html = "<div><style>.x{color:red}</style><p>Hello</p></div>"
    result = clean_html(html)
    assert "<style>" not in result
    assert "Hello" in result


def test_strips_inline_style() -> None:
    html = '<div style="color:red"><p>Hello</p></div>'
    result = clean_html(html)
    assert "style=" not in result
    assert "Hello" in result


def test_strips_comments() -> None:
    html = "<div><!-- secret --><p>Hello</p></div>"
    result = clean_html(html)
    assert "secret" not in result
    assert "Hello" in result


def test_preserves_structure() -> None:
    html = "<div><ul><li>One</li><li>Two</li></ul></div>"
    result = clean_html(html)
    assert "<li>" in result
    assert "One" in result
    assert "Two" in result


def test_max_depth_truncates() -> None:
    html = "<div><ul><li><span>Deep</span></li></ul></div>"
    result = clean_html(html, max_depth=1)
    assert "<ul>" in result  # depth 1: direct children kept
    assert "<li>" not in result  # depth 2+: removed


def test_max_depth_zero_no_limit() -> None:
    html = "<div><ul><li><span>Deep</span></li></ul></div>"
    result = clean_html(html, max_depth=0)
    assert "Deep" in result


def test_max_depth_two() -> None:
    html = "<div><ul><li><span>Deep</span></li></ul></div>"
    result = clean_html(html, max_depth=2)
    assert "<ul>" in result
    assert "<li>" in result
    assert "<span>" not in result
