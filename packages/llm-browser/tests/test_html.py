"""Tests for HTML cleaning utilities."""

import pytest
from lxml.html import fragment_fromstring

from llm_browser.html import SanitizeLevel, sanitize_html_fragment


def test_strips_script_tags() -> None:
    html = "<div><script>alert('x')</script><p>Hello</p></div>"
    result = sanitize_html_fragment(html)
    assert "<script>" not in result
    assert "Hello" in result


def test_strips_style_tags() -> None:
    html = "<div><style>.x{color:red}</style><p>Hello</p></div>"
    result = sanitize_html_fragment(html)
    assert "<style>" not in result
    assert "Hello" in result


def test_strips_inline_style() -> None:
    html = '<div style="color:red"><p>Hello</p></div>'
    result = sanitize_html_fragment(html)
    assert "style=" not in result
    assert "Hello" in result


def test_strips_comments() -> None:
    html = "<div><!-- secret --><p>Hello</p></div>"
    result = sanitize_html_fragment(html)
    assert "secret" not in result
    assert "Hello" in result


def test_preserves_structure() -> None:
    html = "<div><ul><li>One</li><li>Two</li></ul></div>"
    result = sanitize_html_fragment(html)
    assert "<li>" in result
    assert "One" in result
    assert "Two" in result


def test_max_depth_truncates() -> None:
    html = "<div><ul><li><span>Deep</span></li></ul></div>"
    result = sanitize_html_fragment(html, max_depth=1)
    assert "<ul>" in result  # depth 1: direct children kept
    assert "<li>" not in result  # depth 2+: removed


def test_max_depth_zero_no_limit() -> None:
    html = "<div><ul><li><span>Deep</span></li></ul></div>"
    result = sanitize_html_fragment(html, max_depth=0)
    assert "Deep" in result


def test_max_depth_two() -> None:
    html = "<div><ul><li><span>Deep</span></li></ul></div>"
    result = sanitize_html_fragment(html, max_depth=2)
    assert "<ul>" in result
    assert "<li>" in result
    assert "<span>" not in result


SAMPLE = """<main id="content" class="page page--article" data-track="art-42" style="margin:0">
  <!-- header -->
  <header class="hdr">
    <a href="/" class="logo"><img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAUA" alt="Site" width="40"></a>
    <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5z"/></svg>
    <nav aria-label="Main"><span class="x"><span><a href="/news" data-nav="1">News</a></span></span></nav>
  </header>
  <article class="body" data-id="42" itemscope itemtype="https://schema.org/Article">
    <h1 class="title">Rates hold steady</h1>
    <p class="lead" onclick="track()">The bank kept its rate at <b>4.5%</b>.
       Read <a href="https://example.com/x?utm=1" target="_blank" rel="noopener">more</a>.</p>
    <div><div><span class="ad-slot" data-ad="top"></span></div></div>
    <iframe src="https://ads.example.com/f" title="ad"></iframe>
    <form action="/login" method="post"><input type="password" name="pw"><button type="submit">Sign in</button></form>
    <script>window.dataLayer=[{page:"art"}]</script>
    <style>.lead{font-weight:bold}</style>
  </article>
</main>"""


@pytest.fixture
def sanitized() -> dict[SanitizeLevel, str]:
    return {
        level: sanitize_html_fragment(SAMPLE, level=level) for level in SanitizeLevel
    }


@pytest.mark.parametrize("level", list(SanitizeLevel))
def test_root_element_is_preserved(level: SanitizeLevel) -> None:
    tree = fragment_fromstring(sanitize_html_fragment(SAMPLE, level=level))
    assert tree.tag == "main"
    assert tree.get("id") == "content"


@pytest.mark.parametrize(
    "fragment",
    [
        "<main id='x'>hi</main>",
        "<dialog id='d'>hi</dialog>",
        "<picture id='p'>hi</picture>",
    ],
)
def test_unknown_tags_are_not_rewritten(fragment: str) -> None:
    tree = fragment_fromstring(sanitize_html_fragment(fragment))
    assert tree.tag != "div"
    assert tree.get("id") is not None


@pytest.mark.parametrize(
    "needle", ['data-track="art-42"', "<svg", "<path", 'data-ad="top"']
)
def test_low_keeps_everything_non_executable(
    sanitized: dict[SanitizeLevel, str], needle: str
) -> None:
    assert needle in sanitized[SanitizeLevel.LOW]


@pytest.mark.parametrize(
    "needle", ["<svg", "<path", "data-track", "data-ad", "aria-label", "itemscope"]
)
def test_medium_drops_decorative_and_custom_attrs(
    sanitized: dict[SanitizeLevel, str], needle: str
) -> None:
    assert needle not in sanitized[SanitizeLevel.MEDIUM]


@pytest.mark.parametrize(
    "needle",
    [
        'href="/news"',
        'src="https://ads.example.com/f"',
        'title="ad"',
        'src="data:image/png"',
        "<form",
        '<input type="password" name="pw">',
    ],
)
def test_medium_keeps_navigation_and_form_structure(
    sanitized: dict[SanitizeLevel, str], needle: str
) -> None:
    assert needle in sanitized[SanitizeLevel.MEDIUM]


def test_medium_truncates_data_uri(sanitized: dict[SanitizeLevel, str]) -> None:
    assert "base64" not in sanitized[SanitizeLevel.MEDIUM]


def test_high_strips_every_url(sanitized: dict[SanitizeLevel, str]) -> None:
    tree = fragment_fromstring(sanitized[SanitizeLevel.HIGH])
    assert all(link.get("href") is None for link in tree.iter("a"))
    assert all(image.get("src") is None for image in tree.iter("img"))
    frame = next(tree.iter("iframe"))
    assert dict(frame.attrib) == {"title": "ad"}


def test_xhigh_keeps_only_allowlisted_attrs(
    sanitized: dict[SanitizeLevel, str],
) -> None:
    tree = fragment_fromstring(sanitized[SanitizeLevel.XHIGH])
    present = {key for node in tree.iter() for key in node.attrib}
    assert present == {"id", "alt", "title", "type", "name"}


def test_xhigh_iframe_keeps_only_title(sanitized: dict[SanitizeLevel, str]) -> None:
    frame = next(fragment_fromstring(sanitized[SanitizeLevel.XHIGH]).iter("iframe"))
    assert dict(frame.attrib) == {"title": "ad"}


def test_xhigh_drops_empty_wrappers(sanitized: dict[SanitizeLevel, str]) -> None:
    assert "ad-slot" not in sanitized[SanitizeLevel.XHIGH]
    assert "<div>" not in sanitized[SanitizeLevel.XHIGH]


def test_xhigh_unwraps_single_child_wrappers(
    sanitized: dict[SanitizeLevel, str],
) -> None:
    assert "<nav><a>News</a></nav>" in sanitized[SanitizeLevel.XHIGH]


@pytest.mark.parametrize("level", list(SanitizeLevel))
def test_whitespace_is_collapsed(level: SanitizeLevel) -> None:
    result = sanitize_html_fragment(SAMPLE, level=level)
    assert "\n" not in result
    assert "  " not in result


@pytest.mark.parametrize("level", list(SanitizeLevel))
def test_preformatted_whitespace_survives(level: SanitizeLevel) -> None:
    result = sanitize_html_fragment(
        "<main id='c'><pre>  a\n b</pre></main>", level=level
    )
    assert "<pre>  a\n b</pre>" in result


@pytest.mark.parametrize("level", list(SanitizeLevel))
def test_preformatted_tail_is_collapsed(level: SanitizeLevel) -> None:
    result = sanitize_html_fragment(
        "<div><pre>  a\n b</pre>  x  y  </div>", level=level
    )
    assert result == "<div><pre>  a\n b</pre> x y </div>"


def test_higher_levels_shrink_output(sanitized: dict[SanitizeLevel, str]) -> None:
    assert (
        len(sanitized[SanitizeLevel.MEDIUM])
        >= len(sanitized[SanitizeLevel.HIGH])
        >= len(sanitized[SanitizeLevel.XHIGH])
    )
