"""Tests for the 12 minimal declarative actions."""

import ast
import base64
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from llm_browser import actions, flows, steps
from llm_browser import session as session_module
from llm_browser.actions import execute_action
from llm_browser.results import BytesResult, ParsedResult, TextResult
from llm_browser.behavior import Behavior, Jitter
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
    ScrollStep,
    SelectStep,
    TypeStep,
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


@pytest.fixture
def input_session(tmp_path: object) -> MagicMock:
    """A session mock: input actions must not reach past it to a driver."""
    s = MagicMock(spec=BrowserSession)
    s.behavior = Behavior.off()
    s.behavior_runtime = s.behavior.runtime()
    return s


# --- input actions ---
#
# These are one-liners onto the session, so they are checked against a session
# mock: what an input step must do is call the right session method with the
# step's own arguments. How that reaches the driver is
# ``tests/test_session_input.py``.


def test_click(input_session: MagicMock) -> None:
    step = ClickStep(name="s", action="click", selector="#btn", timeout=5_000)
    execute_action(input_session, step)
    input_session.click.assert_called_once_with(
        step.selector, dispatch=False, timeout=5_000
    )


def test_click_dispatch(input_session: MagicMock) -> None:
    step = ClickStep(name="s", action="click", selector="#btn", dispatch=True)
    execute_action(input_session, step)
    assert input_session.click.call_args.kwargs["dispatch"] is True


def test_fill(input_session: MagicMock) -> None:
    step = FillStep(name="s", action="fill", selector="#input", value="hello")
    execute_action(input_session, step)
    input_session.fill.assert_called_once_with(
        step.selector, "hello", timeout=step.timeout
    )


def test_type(input_session: MagicMock) -> None:
    step = TypeStep(
        name="s", action="type", selector="#search", value="query", delay=50
    )
    execute_action(input_session, step)
    input_session.type.assert_called_once_with(
        step.selector, "query", delay_ms=50, timeout=step.timeout
    )


def test_select(input_session: MagicMock) -> None:
    step = SelectStep(name="s", action="select", selector="#dropdown", value="opt2")
    execute_action(input_session, step)
    input_session.select_option.assert_called_once_with(
        step.selector, "opt2", timeout=step.timeout
    )


def test_check(input_session: MagicMock) -> None:
    step = CheckStep(name="s", action="check", selector="#cb")
    execute_action(input_session, step)
    input_session.set_checked.assert_called_once_with(
        step.selector, True, timeout=step.timeout
    )


def test_uncheck(input_session: MagicMock) -> None:
    step = CheckStep(name="s", action="check", selector="#cb", checked=False)
    execute_action(input_session, step)
    assert input_session.set_checked.call_args.args[1] is False


# --- pick ---


def test_pick(session: BrowserSession) -> None:
    locator = MagicMock()
    locator.count.return_value = 2
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


PNG = b"\x89PNG\r\n\x1a\nfake"


def test_screenshot_returns_png_bytes(session: BrowserSession) -> None:
    session._page.screenshot.return_value = PNG  # type: ignore[union-attr]
    step = ScreenshotStep(name="s", action="screenshot")
    result = execute_action(session, step)
    assert isinstance(result, BytesResult)
    assert result.content == PNG
    assert result.name == "s.png"
    assert result.media_type == "image/png"


def test_screenshot_path_is_ignored_by_the_runner(
    session: BrowserSession, tmp_path: Path
) -> None:
    """``path:`` is an instruction to the CLI; the step itself writes nothing."""
    session._page.screenshot.return_value = PNG  # type: ignore[union-attr]
    target = tmp_path / "nested" / "shot.png"
    step = ScreenshotStep(name="s", action="screenshot", path=str(target))
    result = execute_action(session, step)
    assert isinstance(result, BytesResult)
    assert not target.parent.exists()


def test_screenshot_selector_captures_only_that_element(
    session: BrowserSession,
) -> None:
    element = session._page.locator.return_value.first  # type: ignore[union-attr]
    element.screenshot.return_value = PNG
    step = ScreenshotStep(name="s", action="screenshot", selector="#logo")

    result = execute_action(session, step)

    assert isinstance(result, BytesResult)
    assert result.content == PNG
    element.screenshot.assert_called_once_with()
    session._page.screenshot.assert_not_called()  # type: ignore[union-attr]


def test_screenshot_bytes_are_base64_in_json_mode(session: BrowserSession) -> None:
    session._page.screenshot.return_value = PNG  # type: ignore[union-attr]
    result = execute_action(session, ScreenshotStep(name="s", action="screenshot"))
    dumped = result.model_dump(mode="json")
    assert dumped["content"] == base64.b64encode(PNG).decode()
    assert result.model_dump()["content"] == PNG


def _rows_locator(session: BrowserSession, rows: list[dict[str, object]]) -> MagicMock:
    """Make the page's row locator return ``rows`` from its page evaluation."""
    locator = MagicMock()
    locator.evaluate_all.return_value = rows
    session._page.locator.return_value = locator  # type: ignore[union-attr]
    return locator


# --- read ---


def test_read(session: BrowserSession) -> None:
    locator = _rows_locator(session, [{"name": "Alice"}])

    from llm_browser.results import ExtractedRow

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
    script, spec = locator.evaluate_all.call_args.args
    assert "querySelector" in script
    assert spec == {"name": {"child_selector": "td", "attribute": "textContent"}}


def test_read_fails_when_the_page_answered_with_too_few_rows(
    session: BrowserSession,
) -> None:
    """A page still hydrating answers with nothing and looks successful."""
    from llm_browser.actions import ErrorResult

    _rows_locator(session, [{"name": "Alice"}, {"name": None}])
    step = ReadStep(name="s", action="read", selector="tr", min_rows=2)
    result = execute_action(session, step)
    assert isinstance(result, ErrorResult)
    assert result.message == "Expected \u22652 rows, got 1"


def test_read_fails_when_the_rows_hold_too_little_text(
    session: BrowserSession,
) -> None:
    from llm_browser.actions import ErrorResult

    _rows_locator(session, [{"name": "Alice"}])
    step = ReadStep(name="s", action="read", selector="tr", min_chars=20)
    result = execute_action(session, step)
    assert isinstance(result, ErrorResult)
    assert result.message == "Expected \u226520 chars, got 5"


def test_a_minimum_a_row_meets_is_no_failure(session: BrowserSession) -> None:
    _rows_locator(session, [{"name": "Alice"}])
    step = ReadStep(name="s", action="read", selector="tr", min_rows=1, min_chars=5)
    assert isinstance(execute_action(session, step), ParsedResult)


def test_an_optional_read_downgrades_an_unmet_minimum_to_a_skip(
    session: BrowserSession,
) -> None:
    from llm_browser.actions import SkippedResult

    _rows_locator(session, [{"name": None}])
    step = ReadStep(name="s", action="read", selector="tr", min_rows=1, optional=True)
    result = execute_action(session, step)
    assert isinstance(result, SkippedResult)
    assert result.reason == "ValueError: Expected \u22651 rows, got 0"


# --- parse (typed schema action) ---


def test_parse_returns_typed_rows(session: BrowserSession, tmp_path: Path) -> None:
    """The parse action loads a YAML schema and emits coerced typed rows."""
    import yaml

    from llm_browser.actions import ParsedResult
    from llm_browser.models import ParseStep

    schema = tmp_path / "repo.yaml"
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

    _rows_locator(session, [{"name": "foo", "stars": "42"}])

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


def test_read_path_is_ignored_by_the_runner(
    session: BrowserSession, tmp_path: Path
) -> None:
    """``path:`` is an instruction to the CLI; the step returns the rows."""
    _rows_locator(session, [{"name": "Alice"}])

    target = tmp_path / "rows.json"
    step = ReadStep(
        name="s",
        action="read",
        selector="tr",
        extract={"name": {"child_selector": "td", "attribute": "textContent"}},
        path=str(target),
    )
    result = execute_action(session, step)
    assert isinstance(result, ParsedResult)
    assert not target.exists()


def test_parse_path_is_ignored_by_the_runner(
    session: BrowserSession, tmp_path: Path
) -> None:
    """``path:`` is an instruction to the CLI; the step returns the rows."""
    import yaml

    from llm_browser.models import ParseStep

    schema = tmp_path / "repo.yaml"
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

    _rows_locator(session, [{"name": "foo", "stars": "42"}])

    target = tmp_path / "rows.json"
    step = ParseStep(
        name="s",
        action="parse",
        selector="tr.row",
        schema_path=str(schema),
        path=str(target),
    )
    result = execute_action(session, step)
    assert isinstance(result, ParsedResult)
    assert [row.model_dump() for row in result.rows if row] == [
        {"name": "foo", "stars": 42}
    ]
    assert not target.exists()


# --- dom ---


def test_dom(session: BrowserSession) -> None:
    locator = _single_locator()
    locator.first.evaluate.return_value = "<div><p>Hello</p></div>"
    session._page.locator.return_value = locator  # type: ignore[union-attr]

    step = DomStep(name="s", action="dom", selector="#content")
    result = execute_action(session, step)
    assert isinstance(result, TextResult)
    assert "Hello" in result.text


def test_dom_sanitizes_at_the_level_the_step_asked_for(
    session: BrowserSession,
) -> None:
    locator = _single_locator()
    locator.first.evaluate.return_value = '<div><a href="/next">Next</a></div>'
    session._page.locator.return_value = locator  # type: ignore[union-attr]

    step = DomStep(name="s", action="dom", selector="#content", level="high")
    result = execute_action(session, step)
    assert isinstance(result, TextResult)
    assert "href" not in result.text


def test_dom_fails_when_the_snippet_is_shorter_than_expected(
    session: BrowserSession,
) -> None:
    from llm_browser.actions import ErrorResult

    locator = _single_locator()
    locator.first.evaluate.return_value = "<div></div>"
    session._page.locator.return_value = locator  # type: ignore[union-attr]

    step = DomStep(name="s", action="dom", selector="#content", min_chars=100)
    result = execute_action(session, step)
    assert isinstance(result, ErrorResult)
    assert result.message == "Expected \u2265100 chars, got 11"


def test_dom_on_a_body_fragment_returns_the_body(session: BrowserSession) -> None:
    """`<body>` outerHTML is the fragment lxml used to refuse."""
    locator = _single_locator()
    locator.first.evaluate.return_value = (
        "<body><noscript>n</noscript><div>Hi</div><script>x()</script></body>"
    )
    session._page.locator.return_value = locator  # type: ignore[union-attr]

    result = execute_action(session, DomStep(name="s", action="dom", selector="body"))
    assert isinstance(result, TextResult)
    assert result.text.startswith("<body>")
    assert "Hi" in result.text


def test_dom_path_is_ignored_by_the_runner(
    session: BrowserSession, tmp_path: Path
) -> None:
    """``path:`` is an instruction to the CLI; the step returns the text."""
    locator = _single_locator()
    locator.first.evaluate.return_value = "<section><p>Captured</p></section>"
    session._page.locator.return_value = locator  # type: ignore[union-attr]

    target = tmp_path / "captures" / "snippet.html"
    step = DomStep(name="s", action="dom", selector="#content", path=str(target))
    result = execute_action(session, step)

    assert isinstance(result, TextResult)
    assert "Captured" in result.text
    assert not target.parent.exists()


# --- download ---


def _arm_download(session: BrowserSession, tmp_path: Path, payload: bytes) -> MagicMock:
    """A Playwright ``Download`` whose spool file really exists on disk."""
    from contextlib import contextmanager

    page = session._page

    spooled = tmp_path / "spool" / "download.bin"
    spooled.parent.mkdir()
    spooled.write_bytes(payload)

    mock_download = MagicMock()
    mock_download.suggested_filename = "report.csv"
    mock_download.path.return_value = str(spooled)
    mock_download.delete.side_effect = spooled.unlink

    @contextmanager
    def fake_expect_download(timeout=None):  # type: ignore[no-untyped-def]
        page.expect_download_timeout = timeout
        yield MagicMock(value=mock_download)

    session._page.expect_download = fake_expect_download  # type: ignore[union-attr]
    return mock_download


def test_download_returns_bytes(session: BrowserSession, tmp_path: Path) -> None:
    mock_download = _arm_download(session, tmp_path, b"col\n1\n")
    step = DownloadStep(name="s", action="download", selector="#dl-link")
    result = execute_action(session, step)
    assert isinstance(result, BytesResult)
    assert result.content == b"col\n1\n"
    assert result.name == "report.csv"
    assert result.media_type == "text/csv"
    mock_download.delete.assert_called_once()


def test_download_leaves_no_spool_file_behind(
    session: BrowserSession, tmp_path: Path
) -> None:
    """Playwright can only spool a download to a file of its own; the driver
    deletes it before returning."""
    _arm_download(session, tmp_path, b"payload")
    execute_action(session, DownloadStep(name="s", action="download", selector="#a"))
    assert list((tmp_path / "spool").iterdir()) == []


def test_download_honours_the_step_timeout(
    session: BrowserSession, tmp_path: Path
) -> None:
    """Without this the step's budget bounds `find` only and Playwright's own
    30s default takes over for the wait that matters."""
    _arm_download(session, tmp_path, b"payload")
    step = DownloadStep(name="s", action="download", selector="#dl", timeout=2500)
    execute_action(session, step)
    assert session._page.expect_download_timeout == 2500  # type: ignore[union-attr]


def test_a_download_that_fails_is_a_step_failure(
    session: BrowserSession, tmp_path: Path
) -> None:
    """Playwright raises its own `Error` from `path()` on a cancelled
    download; raw, it would unwind out of `run_flow` instead of coming back
    as a failed step."""
    from llm_browser.results import ErrorResult

    mock_download = _arm_download(session, tmp_path, b"payload")
    mock_download.path.side_effect = RuntimeError("download was canceled")
    result = execute_action(
        session, DownloadStep(name="s", action="download", selector="#dl")
    )
    assert isinstance(result, ErrorResult)
    assert result.error == "ValueError"
    assert "download did not complete" in result.message
    mock_download.delete.assert_called_once()


def test_download_path_is_ignored_by_the_runner(
    session: BrowserSession, tmp_path: Path
) -> None:
    _arm_download(session, tmp_path, b"payload")
    dest = tmp_path / "downloads" / "file.pdf"
    step = DownloadStep(
        name="s", action="download", selector="#dl-link", path=str(dest)
    )
    result = execute_action(session, step)
    assert isinstance(result, BytesResult)
    assert not dest.parent.exists()


# --- press ---


def test_press_on_selector(input_session: MagicMock) -> None:
    step = PressStep(name="s", action="press", selector="#box", key="Enter")
    execute_action(input_session, step)
    input_session.press.assert_called_once_with(
        step.selector, "Enter", timeout=step.timeout
    )


def test_press_focused(input_session: MagicMock) -> None:
    step = PressStep(name="s", action="press", key="Enter")
    execute_action(input_session, step)
    assert input_session.press.call_args.args[0] is None


def test_press_requires_key() -> None:
    """``key`` is required at construction; bad steps fail before any browser
    work, surfaced via Pydantic ValidationError."""
    with pytest.raises(ValidationError):
        PressStep(name="s", action="press")


# --- wait ---


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
    wait = MagicMock()
    session.wait_for_element = wait  # type: ignore[method-assign]

    execute_action(session, step)

    wait.assert_called_once_with("#btn", state="visible", timeout=30_000)


# --- scroll ---


@pytest.mark.parametrize(
    "kwargs, expected_calls, expected_delta",
    [
        ({}, 1, 600),
        ({"delta": -400}, 1, -400),
        ({"delta": 500, "times": 4}, 4, 500),
    ],
)
def test_scroll_wheels_once_per_tick(
    session: BrowserSession,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, int],
    expected_calls: int,
    expected_delta: int,
) -> None:
    monkeypatch.setattr("llm_browser.behavior.time.sleep", lambda _s: None)
    step = ScrollStep(name="s", action="scroll", **kwargs)
    execute_action(session, step)
    mouse = session._page.mouse  # type: ignore[union-attr]
    assert mouse.wheel.call_count == expected_calls
    mouse.wheel.assert_called_with(0, expected_delta)


def test_scroll_pauses_between_ticks(
    session: BrowserSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[float] = []
    monkeypatch.setattr("llm_browser.behavior.time.sleep", lambda s: calls.append(s))
    step = ScrollStep(
        name="s", action="scroll", times=3, pause=Jitter(min_ms=10, max_ms=20)
    )
    execute_action(session, step)
    pauses = [c for c in calls if c > 0]
    # Only between ticks: execute_action already applies the post-action pause.
    assert len(pauses) == 2
    assert all(0.010 <= c <= 0.020 for c in pauses)


# --- unknown action ---


def test_unknown_action_raises() -> None:
    with pytest.raises(ValidationError):
        validate_step({"name": "s", "action": "nonexistent"})


# --- layering ---


# Every driver method that drives the page from a policy decision — humanized
# or plain, trusted or dispatched. Reading one of these off a driver outside
# ``session_input`` is a second copy of that decision.
DRIVER_INPUT_METHODS = frozenset(
    {
        "click",
        "fill",
        "type",
        "press",
        "press_focused",
        "select_option",
        "set_checked",
        "dispatch_event",
        "humanized_click",
        "humanized_type",
    }
)


def driver_attributes(module: object) -> list[ast.Attribute]:
    tree = ast.parse(Path(module.__file__).read_text())  # type: ignore[attr-defined]
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "driver"
    ]


@pytest.mark.parametrize("module", [actions, steps, flows])
def test_the_layers_above_the_session_never_touch_the_driver(module: object) -> None:
    """steps -> actions -> session -> driver. An action that reaches for
    ``session.driver`` skips the session's pacing and humanization, so the
    layering is asserted on the source itself rather than left to review."""
    reads = driver_attributes(module)
    assert reads == [], [ast.unparse(node) for node in reads]


def test_only_session_input_drives_the_page() -> None:
    """``session.py`` may hold the driver — it owns the lifecycle — but the
    input primitives are ``session_input``'s alone. A second call site is a
    second humanized-vs-plain decision, and it drifts."""
    tree = ast.parse(Path(session_module.__file__).read_text())
    calls = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr in DRIVER_INPUT_METHODS
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "driver"
    ]
    assert calls == []


def test_parse_coerces_decimal_and_date_rows(
    session: BrowserSession, tmp_path: Path
) -> None:
    """A schema may declare types ``json.dumps`` cannot represent; the rows
    have to survive a JSON-mode dump for a caller to serialize them."""
    import yaml

    from llm_browser.models import ParseStep

    schema = tmp_path / "invoice.yaml"
    schema.write_text(
        yaml.safe_dump(
            {
                "name": "Invoice",
                "fields": {
                    "total": {"type": "Decimal", "child_selector": "td.total"},
                    "due": {"type": "date", "child_selector": "td.due"},
                },
            }
        )
    )

    _rows_locator(session, [{"total": "10.25", "due": "2024-03-01"}])

    step = ParseStep(
        name="s", action="parse", selector="tr.row", schema_path=str(schema)
    )
    result = execute_action(session, step)
    assert isinstance(result, ParsedResult)
    assert [row.model_dump(mode="json") for row in result.rows if row] == [
        {"total": "10.25", "due": "2024-03-01"}
    ]


def test_a_type_error_inside_an_optional_step_still_reaches_the_developer(
    session: BrowserSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression the narrow catch exists for: a latent bug in an action
    must not come back as `SkippedResult` and report the flow a success."""

    def boom(*args: object, **kwargs: object) -> None:
        raise TypeError("len() of unsized object")

    monkeypatch.setattr(session, "click", boom)
    step = ClickStep(name="s", action="click", selector="#x", optional=True)
    with pytest.raises(TypeError, match=r"len\(\) of unsized object"):
        execute_action(session, step)
