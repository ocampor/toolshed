"""Tests for full-page DOM sanitization and checkpoint capture modes."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from llm_browser.flows import FlowRunner
from llm_browser.html import sanitize_page_html
from llm_browser.session import BrowserSession


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


def test_keeps_form_elements() -> None:
    out = sanitize_page_html(_wrap('<form><input name="q"></form>'))
    assert "<form" in out
    assert '<input name="q"' in out


@pytest.fixture
def checkpoint_flow(tmp_path: Path) -> Path:
    path = tmp_path / "flow.yaml"
    steps: list[dict[str, Any]] = [
        {"name": "s1", "eval": "getVal()", "checkpoint": True},
    ]
    path.write_text(yaml.dump({"steps": steps}))
    return path


def _mock_capture_session(tmp_path: Path, capture: str) -> MagicMock:
    from llm_browser.behavior import Behavior

    session = MagicMock(spec=BrowserSession)
    session.session_dir = tmp_path
    session.behavior = Behavior.off()
    session._behavior_runtime = session.behavior.runtime()
    session.capture = capture
    session.take_screenshot.return_value = tmp_path / "screenshot.png"
    session.take_dom_snapshot.return_value = tmp_path / "dom.html"
    session.get_page.return_value.evaluate.return_value = "v"
    session.element_exists.return_value = True
    return session


def test_checkpoint_default_only_screenshot(
    tmp_path: Path, checkpoint_flow: Path
) -> None:
    session = _mock_capture_session(tmp_path, "screenshot")
    result = FlowRunner(session).run(checkpoint_flow, {})
    assert result.screenshot is not None
    assert result.dom is None
    session.take_dom_snapshot.assert_not_called()


def test_checkpoint_dom_only(tmp_path: Path, checkpoint_flow: Path) -> None:
    session = _mock_capture_session(tmp_path, "dom")
    result = FlowRunner(session).run(checkpoint_flow, {})
    assert result.screenshot is None
    assert result.dom == str(tmp_path / "dom.html")
    session.take_screenshot.assert_not_called()


def test_checkpoint_both(tmp_path: Path, checkpoint_flow: Path) -> None:
    session = _mock_capture_session(tmp_path, "both")
    result = FlowRunner(session).run(checkpoint_flow, {})
    assert result.screenshot is not None
    assert result.dom is not None
    session.take_screenshot.assert_called_once()
    session.take_dom_snapshot.assert_called_once()


def test_take_dom_snapshot_writes_file(tmp_path: Path) -> None:
    session = BrowserSession(state_dir=tmp_path, capture="dom")
    mock_page = MagicMock()
    mock_page.content.return_value = _wrap("<p>hello</p><script>x()</script>")
    session._page = mock_page
    path = session.take_dom_snapshot()
    assert path.exists()
    content = path.read_text()
    assert "hello" in content
    assert "script" not in content
