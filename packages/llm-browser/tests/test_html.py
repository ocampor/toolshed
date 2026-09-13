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
    "needle",
    [
        'data-track="art-42"',
        'data-ad="top"',
        'aria-label="Main"',
        "itemscope",
        'src="data:image/png;base64',
    ],
)
def test_low_keeps_custom_attributes(
    sanitized: dict[SanitizeLevel, str], needle: str
) -> None:
    assert needle in sanitized[SanitizeLevel.LOW]


@pytest.mark.parametrize("level", list(SanitizeLevel))
@pytest.mark.parametrize("needle", ["<script", "<style"])
def test_every_level_kills_executable_tags(level: SanitizeLevel, needle: str) -> None:
    assert needle not in sanitize_html_fragment(SAMPLE, level=level)


def test_low_keeps_svg(sanitized: dict[SanitizeLevel, str]) -> None:
    assert "<svg" in sanitized[SanitizeLevel.LOW]
    assert "<path" in sanitized[SanitizeLevel.LOW]


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


def test_xhigh_output_is_exact(sanitized: dict[SanitizeLevel, str]) -> None:
    assert sanitized[SanitizeLevel.XHIGH] == (
        '<main id="content">'
        '<header><a><img alt="Site"></a><nav><a>News</a></nav></header>'
        "<article><h1>Rates hold steady</h1>"
        "<p>The bank kept its rate at <b>4.5%</b>. Read <a>more</a>.</p>"
        '<iframe title="ad"></iframe>'
        '<form><input type="password" name="pw">'
        '<button type="submit">Sign in</button></form></article></main>'
    )


def test_xhigh_strips_structural_tags_but_keeps_their_text() -> None:
    result = sanitize_html_fragment(
        "<article><div class='w'>a<span>b</span><section>c</section></div></article>",
        level=SanitizeLevel.XHIGH,
    )
    assert result == "<article>abc</article>"


def test_xhigh_keeps_a_structural_root() -> None:
    result = sanitize_html_fragment(
        "<div id='c'><span>a</span> b</div>", level=SanitizeLevel.XHIGH
    )
    assert result == '<div id="c">a b</div>'


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


def test_a_body_fragment_sanitizes_to_the_body_element() -> None:
    """`dom body` hands lxml an outerHTML whose root its fragment parser
    strips, leaving the children as several roots it then refuses."""
    html = "<body><noscript>n</noscript><div>Hi</div><script>x()</script></body>"
    result = sanitize_html_fragment(html)
    assert result.startswith("<body>")
    assert "Hi" in result
    assert "<script>" not in result


def test_an_html_fragment_sanitizes_to_the_html_element() -> None:
    html = "<html><head><title>T</title></head><body><div>Hi</div></body></html>"
    result = sanitize_html_fragment(html)
    assert result.startswith("<html>")
    assert "Hi" in result


@pytest.mark.parametrize("html", ["", "<body"])
def test_unparseable_html_is_a_step_failure(html: str) -> None:
    """lxml raises a ParserError (a SyntaxError) for one and hands back a
    document with no `.body` for the other; both would escape
    `is_step_failure` and crash the run instead of failing the step."""
    with pytest.raises(ValueError, match="cannot parse HTML"):
        sanitize_html_fragment(html)
