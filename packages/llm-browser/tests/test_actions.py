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
    PressStep,
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


def test_click_dispatch(session: BrowserSession) -> None:
    step = ClickStep(name="s", action="click", selector="#btn", dispatch=True)
    execute_action(session, step)
    locator = session._page.locator.return_value  # type: ignore[union-attr]
    locator.first.dispatch_event.assert_called_once_with("click")
    locator.first.click.assert_not_called()


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

    from llm_browser.actions import ExtractedRow, ParsedResult

    step = ReadStep(
        name="s",
        action="read",
        selector="tr",
        extract={"name": {"child_selector": "td", "attribute": "textContent"}},
    )
    result = execute_action(session, step)
    assert isinstance(result, ParsedResult)
    assert len(result.rows) == 1
    row = result.rows[0]
    assert isinstance(row, ExtractedRow)
    assert row.model_dump() == {"name": "Alice"}


# --- parse (typed schema action) ---


def test_parse_returns_typed_rows(session: BrowserSession, tmp_path: object) -> None:
    """The parse action loads a YAML schema and emits coerced typed rows."""
    from pathlib import Path

    import yaml

    from llm_browser.actions import ParsedResult
    from llm_browser.models import ParseStep

    schema = Path(str(tmp_path)) / "repo.yaml"
    schema.write_text(
        yaml.safe_dump(
            {
                "name": "Repo",
                "fields": {
                    "name": {"type": "str", "child_selector": "td.name"},
                    "stars": {"type": "int", "child_selector": "td.stars"},
                },
            }
        )
    )

    # Build a mock that yields one row whose children return string values
    # for the fields the schema asks for.
    def _make_row(fields: dict[str, str]) -> MagicMock:
        row = MagicMock()

        def _resolve(child_sel: str) -> MagicMock:
            child = MagicMock()
            key = child_sel.split(".", 1)[1]
            child.text_content.return_value = fields.get(key)
            return child

        row.locator.side_effect = _resolve
        return row

    locator = MagicMock()
    locator.all.return_value = [_make_row({"name": "foo", "stars": "42"})]
    session._page.locator.return_value = locator  # type: ignore[union-attr]

    step = ParseStep(
        name="s", action="parse", selector="tr.row", schema_path=str(schema)
    )
    result = execute_action(session, step)

    assert isinstance(result, ParsedResult)
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row is not None
    assert row.__class__.__name__ == "Repo"
    assert row.name == "foo"
    assert row.stars == 42
    assert isinstance(row.stars, int)


# --- dom ---


def test_dom(session: BrowserSession) -> None:
    from llm_browser.actions import TextResult

    locator = _single_locator()
    locator.first.evaluate.return_value = "<div><p>Hello</p></div>"
    session._page.locator.return_value = locator  # type: ignore[union-attr]

    step = DomStep(name="s", action="dom", selector="#content")
    result = execute_action(session, step)
    assert isinstance(result, TextResult)
    assert "Hello" in result.text


# --- download ---


def test_download(session: BrowserSession, tmp_path: object) -> None:
    from contextlib import contextmanager
    from pathlib import Path

    dest = Path(str(tmp_path)) / "downloads" / "file.pdf"
    mock_download = MagicMock()

    @contextmanager
    def fake_expect_download():  # type: ignore[no-untyped-def]
        yield MagicMock(value=mock_download)

    session._page.expect_download = fake_expect_download  # type: ignore[union-attr]

    from llm_browser.actions import PathResult

    step = DownloadStep(
        name="s", action="download", selector="#dl-link", path=str(dest)
    )
    result = execute_action(session, step)
    assert isinstance(result, PathResult)
    assert result.path == str(dest)
    mock_download.save_as.assert_called_once_with(str(dest))


def test_download_requires_path() -> None:
    """``path`` is required at construction; bad steps fail before any browser
    work, surfaced via Pydantic ValidationError."""
    with pytest.raises(ValidationError):
        DownloadStep(name="s", action="download", selector="#dl-link")


# --- press ---


def test_press_on_selector(session: BrowserSession) -> None:
    step = PressStep(name="s", action="press", selector="#box", key="Enter")
    execute_action(session, step)
    locator = session._page.locator.return_value  # type: ignore[union-attr]
    locator.first.press.assert_called_once_with("Enter")


def test_press_focused(session: BrowserSession) -> None:
    step = PressStep(name="s", action="press", key="Enter")
    execute_action(session, step)
    session._page.keyboard.press.assert_called_once_with("Enter")  # type: ignore[union-attr]


def test_press_requires_key() -> None:
    """``key`` is required at construction; bad steps fail before any browser
    work, surfaced via Pydantic ValidationError."""
    with pytest.raises(ValidationError):
        PressStep(name="s", action="press")


# --- wait ---


def test_wait(session: BrowserSession) -> None:
    """``wait`` polls a selector until its text stops changing for ``quiet_ms``."""
    from llm_browser.actions import TextResult

    # The Playwright-family driver resolves stability in-page via
    # locator.evaluate(); mock its return.
    locator = _single_locator()
    locator.first.evaluate.return_value = "done"
    session._page.locator.return_value = locator  # type: ignore[union-attr]

    step = WaitStep(name="s", action="wait", selector="#reply", quiet_ms=5, timeout_s=5)
    result = execute_action(session, step)
    assert isinstance(result, TextResult)
    assert result.text == "done"


# --- no action ---


def test_no_action_returns_void(session: BrowserSession) -> None:
    from llm_browser.actions import VoidResult

    step = EvalStep(name="s")
    assert isinstance(execute_action(session, step), VoidResult)


# --- optional flag ---


def test_optional_swallows_timeout(session: BrowserSession) -> None:
    from llm_browser.actions import SkippedResult

    locator = session._page.locator.return_value  # type: ignore[union-attr]
    locator.first.click.side_effect = TimeoutError("element hidden")
    step = ClickStep(name="s", action="click", selector="#missing", optional=True)
    result = execute_action(session, step)
    assert isinstance(result, SkippedResult)
    assert result.skipped is True
    assert result.reason == "TimeoutError: element hidden"


def test_optional_swallows_value_error(session: BrowserSession) -> None:
    from llm_browser.actions import SkippedResult

    locator = session._page.locator.return_value  # type: ignore[union-attr]
    locator.count.return_value = 3  # triggers expect_single ValueError
    step = ClickStep(name="s", action="click", selector=".ambiguous", optional=True)
    result = execute_action(session, step)
    assert isinstance(result, SkippedResult)
    assert result.skipped is True


def test_non_optional_returns_error(session: BrowserSession) -> None:
    from llm_browser.actions import ErrorResult

    locator = session._page.locator.return_value  # type: ignore[union-attr]
    locator.first.click.side_effect = TimeoutError("element hidden")
    step = ClickStep(name="my_step", action="click", selector="#missing")
    result = execute_action(session, step)
    assert isinstance(result, ErrorResult)
    assert result.ok is False
    assert result.error == "TimeoutError"
    assert result.step_name == "my_step"
    assert result.selector == "'#missing'"
    assert result.hint == "element hidden, missing, or slow to render"
    assert result.message == "element hidden"


def test_step_timeout_passed_to_find(session: BrowserSession) -> None:
    step = ClickStep(name="s", action="click", selector="#btn", timeout=30_000)
    execute_action(session, step)
    locator = session._page.locator.return_value  # type: ignore[union-attr]
    # find() calls wait_for on the first locator with the given timeout
    locator.first.wait_for.assert_called_with(state="visible", timeout=30_000)


# --- unknown action ---


def test_unknown_action_raises() -> None:
    with pytest.raises(ValidationError):
        validate_step({"name": "s", "action": "nonexistent"})
