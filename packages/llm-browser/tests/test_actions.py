"""Tests for the 12 minimal declarative actions."""

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from llm_browser.actions import execute_action
from llm_browser.models import (
    CheckStep,
    ClickStep,
    DomStep,
    DownloadStep,
    EvalStep,
    FillStep,
    GotoStep,
    PickStep,
    ReadStep,
    ScreenshotStep,
    SelectStep,
    TypeStep,
    WaitStep,
    validate_step,
)
from llm_browser.session import BrowserSession


def _single_locator() -> MagicMock:
    locator = MagicMock()
    locator.count.return_value = 1
    return locator


@pytest.fixture
def session(tmp_path: object) -> BrowserSession:
    s = BrowserSession(state_dir=tmp_path)  # type: ignore[arg-type]
    mock_page = MagicMock()
    mock_page.locator.return_value = _single_locator()
    s._page = mock_page
    return s


# --- click ---


def test_click(session: BrowserSession) -> None:
    step = ClickStep(name="s", action="click", selector="#btn")
    execute_action(session, step)
    locator = session._page.locator.return_value  # type: ignore[union-attr]
    locator.first.click.assert_called_once()


# --- fill ---


def test_fill(session: BrowserSession) -> None:
    step = FillStep(name="s", action="fill", selector="#input", value="hello")
    execute_action(session, step)
    locator = session._page.locator.return_value  # type: ignore[union-attr]
    locator.first.fill.assert_called_once_with("hello")


# --- type ---


def test_type(session: BrowserSession) -> None:
    step = TypeStep(
        name="s", action="type", selector="#search", value="query", delay=50
    )
    execute_action(session, step)
    locator = session._page.locator.return_value  # type: ignore[union-attr]
    locator.first.type.assert_called_once_with("query", delay=50)


# --- select ---


def test_select(session: BrowserSession) -> None:
    step = SelectStep(name="s", action="select", selector="#dropdown", value="opt2")
    execute_action(session, step)
    locator = session._page.locator.return_value  # type: ignore[union-attr]
    locator.first.select_option.assert_called_once_with("opt2")


# --- check ---


def test_check(session: BrowserSession) -> None:
    step = CheckStep(name="s", action="check", selector="#cb")
    execute_action(session, step)
    locator = session._page.locator.return_value  # type: ignore[union-attr]
    locator.first.check.assert_called_once()


def test_uncheck(session: BrowserSession) -> None:
    step = CheckStep(name="s", action="check", selector="#cb", checked=False)
    execute_action(session, step)
    locator = session._page.locator.return_value  # type: ignore[union-attr]
    locator.first.uncheck.assert_called_once()


# --- pick ---


def test_pick(session: BrowserSession) -> None:
    locator = MagicMock()
    locator.count.return_value = 2
    locator.first.wait_for.return_value = None
    item1 = MagicMock()
    item1.text_content.return_value = "Apple"
    item2 = MagicMock()
    item2.text_content.return_value = "Banana"
    locator.nth.side_effect = lambda i: [item1, item2][i]
    session._page.locator.return_value = locator  # type: ignore[union-attr]

    step = PickStep(name="s", action="pick", selector=".option", value="Banana")
    execute_action(session, step)
    item2.click.assert_called_once()


# --- goto ---


def test_goto(session: BrowserSession) -> None:
    step = GotoStep(name="s", action="goto", url="https://example.com")
    execute_action(session, step)
    session._page.goto.assert_called_once_with(  # type: ignore[union-attr]
        "https://example.com", wait_until="domcontentloaded"
    )


# --- wait ---


def test_wait(session: BrowserSession) -> None:
    step = WaitStep(name="s", action="wait", state="load", timeout=5000)
    execute_action(session, step)
    session._page.wait_for_load_state.assert_called_once_with(  # type: ignore[union-attr]
        "load", timeout=5000
    )


# --- screenshot ---


def test_screenshot(session: BrowserSession) -> None:
    step = ScreenshotStep(name="s", action="screenshot")
    result = execute_action(session, step)
    assert result is not None


# --- read ---


def test_read(session: BrowserSession) -> None:
    row = MagicMock()
    child = MagicMock()
    child.text_content.return_value = "Alice"
    row.locator.return_value = child

    locator = MagicMock()
    locator.all.return_value = [row]
    session._page.locator.return_value = locator  # type: ignore[union-attr]

    step = ReadStep(
        name="s",
        action="read",
        selector="tr",
        extract={"name": {"child_selector": "td", "attribute": "textContent"}},
    )
    result = execute_action(session, step)
    assert result == [{"name": "Alice"}]


# --- dom ---


def test_dom(session: BrowserSession) -> None:
    locator = _single_locator()
    locator.first.evaluate.return_value = "<div><p>Hello</p></div>"
    session._page.locator.return_value = locator  # type: ignore[union-attr]

    step = DomStep(name="s", action="dom", selector="#content")
    result = execute_action(session, step)
    assert "Hello" in result


# --- download ---


def test_download(session: BrowserSession, tmp_path: object) -> None:
    from contextlib import contextmanager
    from pathlib import Path

    dest = Path(str(tmp_path)) / "downloads" / "file.pdf"
    mock_download = MagicMock()

    @contextmanager
    def fake_expect_download():
        yield MagicMock(value=mock_download)

    session._page.expect_download = fake_expect_download  # type: ignore[union-attr]

    step = DownloadStep(
        name="s", action="download", selector="#dl-link", path=str(dest)
    )
    result = execute_action(session, step)
    assert result == str(dest)
    mock_download.save_as.assert_called_once_with(str(dest))


def test_download_requires_path(session: BrowserSession) -> None:
    step = DownloadStep(name="s", action="download", selector="#dl-link")
    with pytest.raises(ValueError, match="path"):
        execute_action(session, step)


# --- no action ---


def test_no_action_returns_none(session: BrowserSession) -> None:
    step = EvalStep(name="s")
    assert execute_action(session, step) is None


# --- unknown action ---


def test_unknown_action_raises() -> None:
    with pytest.raises(ValidationError):
        validate_step({"name": "s", "action": "nonexistent"})
