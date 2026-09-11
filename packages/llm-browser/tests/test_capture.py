"""Tests for full-page DOM sanitization and capture-on-failure modes."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from llm_browser.html import SanitizeLevel, sanitize_page_html
from llm_browser.session import BrowserSession
from tests.conftest import PNG
from tests.flow_helpers import run_flow_file


DOM = "<html><body>captured</body></html>"


def _wrap(body: str) -> str:
    return f"<html><head></head><body>{body}</body></html>"


def test_strips_scripts() -> None:
    out = sanitize_page_html(_wrap("<script>alert(1)</script><p>hi</p>"))
    assert "alert" not in out
    assert "<p>hi</p>" in out


def test_strips_styles() -> None:
    out = sanitize_page_html(_wrap("<style>.x{color:red}</style><p>hi</p>"))
    assert ".x{color:red}" not in out


def test_strips_inline_handlers() -> None:
    out = sanitize_page_html(_wrap('<button onclick="x()">go</button>'))
    assert "onclick" not in out
    assert "go" in out


def test_strips_svg() -> None:
    out = sanitize_page_html(_wrap('<svg><circle r="5"/></svg><p>hi</p>'))
    assert "<svg" not in out
    assert "<circle" not in out
    assert "<p>hi</p>" in out


def test_drops_img_src() -> None:
    out = sanitize_page_html(_wrap('<img src="data:image/png;base64,AAAA">'))
    assert "base64" not in out
    assert "src=" not in out


def test_drops_anchor_href() -> None:
    out = sanitize_page_html(_wrap('<a href="data:text/html,hi">x</a>'))
    assert "data:" not in out
    assert "href=" not in out
    assert ">x</a>" in out


def test_keeps_iframe_title() -> None:
    out = sanitize_page_html(
        _wrap('<iframe src="https://ads.example/f" title="ad"></iframe>')
    )
    assert '<iframe title="ad">' in out
    assert "ads.example" not in out


def test_keeps_unknown_tags() -> None:
    out = sanitize_page_html(_wrap("<main><p>hi</p></main>"))
    assert "<main>" in out


def test_keeps_form_elements() -> None:
    out = sanitize_page_html(_wrap('<form><input name="q"></form>'))
    assert "<form" in out
    assert '<input name="q"' in out


@pytest.fixture
def failing_flow(tmp_path: Path) -> Path:
    path = tmp_path / "failing_flow.yaml"
    steps: list[dict[str, Any]] = [
        {"name": "bad_click", "action": "click", "selector": {"css": "#missing"}},
    ]
    path.write_text(yaml.dump({"steps": steps}))
    return path


def _mock_failing_session(tmp_path: Path, capture: str) -> MagicMock:
    from llm_browser.behavior import Behavior

    session = MagicMock(spec=BrowserSession)
    session.session_dir = tmp_path
    session.behavior = Behavior.off()
    session.behavior_runtime = session.behavior.runtime()
    session.capture = capture
    session.driver = MagicMock()
    session.screenshot_bytes.return_value = PNG
    session.dom_snapshot.return_value = DOM
    session.get_page.return_value = MagicMock()
    session.element_exists.return_value = True
    session.click.side_effect = TimeoutError("element not found")
    return session


@pytest.mark.parametrize(
    "capture, wants_screenshot, wants_dom",
    [
        ("screenshot", True, False),
        ("dom", False, True),
        ("both", True, True),
        ("none", False, False),
    ],
)
def test_failure_capture_modes(
    tmp_path: Path,
    failing_flow: Path,
    capture: str,
    wants_screenshot: bool,
    wants_dom: bool,
) -> None:
    """Captures come back in memory: PNG bytes and sanitized HTML text."""
    session = _mock_failing_session(tmp_path, capture)
    result = run_flow_file(session, failing_flow, {})
    assert not result.data.ok  # type: ignore[union-attr]
    assert result.screenshot == (PNG if wants_screenshot else None)
    assert result.dom == (DOM if wants_dom else None)
    assert session.screenshot_bytes.call_count == int(wants_screenshot)
    assert session.dom_snapshot.call_count == int(wants_dom)
    assert list(tmp_path.iterdir()) == [failing_flow]


def test_failure_screenshot_is_base64_in_json_mode(
    tmp_path: Path, failing_flow: Path
) -> None:
    import base64

    session = _mock_failing_session(tmp_path, "screenshot")
    result = run_flow_file(session, failing_flow, {})
    assert (
        result.model_dump(mode="json")["screenshot"] == base64.b64encode(PNG).decode()
    )


def test_failure_dom_is_redacted(tmp_path: Path, failing_flow: Path) -> None:
    session = _mock_failing_session(tmp_path, "dom")
    session.dom_snapshot.return_value = "<p>token=s3cret</p>"
    result = run_flow_file(session, failing_flow, {}, redact=["s3cret"])
    assert result.dom == "<p>token=***</p>"


def test_dom_snapshot_sanitizes_the_page(tmp_path: Path) -> None:
    session = BrowserSession(state_dir=tmp_path, capture="dom")
    mock_page = MagicMock()
    mock_page.content.return_value = _wrap("<p>hello</p><script>x()</script>")
    session._page = mock_page
    content = session.dom_snapshot()
    assert "hello" in content
    assert "script" not in content
    assert not session.session_dir.exists()


# --- the capture level is the caller's decision ---

LINKED_PAGE = _wrap(
    '<div><a href="https://next.example/step2">next</a>'
    '<img src="data:image/png;base64,AAAABBBB">'
    "<span>text</span></div>"
)


def _snapshot_at(tmp_path: Path, level: SanitizeLevel | None) -> str:
    session = BrowserSession(state_dir=tmp_path, capture="dom")
    page = MagicMock()
    page.content.return_value = LINKED_PAGE
    session._page = page
    return session.dom_snapshot(level)


@pytest.mark.parametrize(
    "level, keeps_href, keeps_span",
    [
        (SanitizeLevel.LOW, True, True),
        (SanitizeLevel.MEDIUM, True, True),
        (SanitizeLevel.HIGH, False, True),
        (SanitizeLevel.XHIGH, False, False),
    ],
)
def test_dom_snapshot_honours_the_level(
    tmp_path: Path, level: SanitizeLevel, keeps_href: bool, keeps_span: bool
) -> None:
    """A page snapshot applies the same per-level passes a `dom` snippet
    does — the level table is one implementation, not two."""
    out = _snapshot_at(tmp_path, level)
    assert ("next.example" in out) is keeps_href, out
    assert ("<span" in out) is keeps_span, out
    assert "next" in out, "the text survives every level"


def test_dom_snapshot_defaults_to_the_session_level(tmp_path: Path) -> None:
    session = BrowserSession(
        state_dir=tmp_path, capture="dom", capture_level=SanitizeLevel.MEDIUM
    )
    page = MagicMock()
    page.content.return_value = LINKED_PAGE
    session._page = page
    assert "next.example" in session.dom_snapshot()
    assert "next.example" not in session.dom_snapshot(SanitizeLevel.HIGH)


def test_the_default_capture_level_is_high(tmp_path: Path) -> None:
    assert BrowserSession(state_dir=tmp_path).capture_level is SanitizeLevel.HIGH
    assert "next.example" not in _snapshot_at(tmp_path, None)


def test_medium_truncates_a_data_uri_in_a_page_snapshot(tmp_path: Path) -> None:
    """The per-level extras apply to a document, not just a fragment."""
    out = _snapshot_at(tmp_path, SanitizeLevel.MEDIUM)
    assert "AAAABBBB" not in out
    assert "data:image/png" in out
