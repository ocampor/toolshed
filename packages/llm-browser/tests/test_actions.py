"""Tests for the 12 minimal declarative actions."""

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from llm_browser import actions, flows, steps
from llm_browser import session as session_module
from llm_browser.actions import execute_action
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


def test_screenshot(session: BrowserSession) -> None:
    step = ScreenshotStep(name="s", action="screenshot")
    result = execute_action(session, step)
    assert result is not None


def test_screenshot_writes_to_explicit_path(
    session: BrowserSession, tmp_path: object
) -> None:
    from pathlib import Path

    from llm_browser.actions import PathResult

    target = Path(str(tmp_path)) / "nested" / "shot.png"
    step = ScreenshotStep(name="s", action="screenshot", path=str(target))
    result = execute_action(session, step)
    assert isinstance(result, PathResult)
    assert result.path == str(target)
    assert target.parent.exists()
    # driver.screenshot delegates to page.screenshot(path=str(target))
    session._page.screenshot.assert_called_once_with(  # type: ignore[union-attr]
        path=str(target), full_page=False
    )


def _rows_locator(session: BrowserSession, rows: list[dict[str, object]]) -> MagicMock:
    """Make the page's row locator return ``rows`` from its page evaluation."""
    locator = MagicMock()
    locator.evaluate_all.return_value = rows
    session._page.locator.return_value = locator  # type: ignore[union-attr]
    return locator


# --- read ---


def test_read(session: BrowserSession) -> None:
    locator = _rows_locator(session, [{"name": "Alice"}])

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
    script, spec = locator.evaluate_all.call_args.args
    assert "querySelector" in script
    assert spec == {"name": {"child_selector": "td", "attribute": "textContent"}}


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


def test_read_writes_to_path(session: BrowserSession, tmp_path: object) -> None:
    """``read`` step with ``path`` dumps rows as JSON for the caller."""
    import json
    from pathlib import Path

    _rows_locator(session, [{"name": "Alice"}])

    target = Path(str(tmp_path)) / "rows.json"
    step = ReadStep(
        name="s",
        action="read",
        selector="tr",
        extract={"name": {"child_selector": "td", "attribute": "textContent"}},
        path=str(target),
    )
    execute_action(session, step)
    assert json.loads(target.read_text()) == [{"name": "Alice"}]


def test_parse_writes_to_path(session: BrowserSession, tmp_path: object) -> None:
    """``parse`` step with ``path`` dumps typed rows as JSON for the caller."""
    import json
    from pathlib import Path

    import yaml

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

    _rows_locator(session, [{"name": "foo", "stars": "42"}])

    target = Path(str(tmp_path)) / "rows.json"
    step = ParseStep(
        name="s",
        action="parse",
        selector="tr.row",
        schema_path=str(schema),
        path=str(target),
    )
    execute_action(session, step)
    assert json.loads(target.read_text()) == [{"name": "foo", "stars": 42}]


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


def test_dom_writes_to_path(session: BrowserSession, tmp_path: object) -> None:
    from pathlib import Path

    from llm_browser.actions import TextResult

    locator = _single_locator()
    locator.first.evaluate.return_value = "<section><p>Captured</p></section>"
    session._page.locator.return_value = locator  # type: ignore[union-attr]

    target = Path(str(tmp_path)) / "captures" / "snippet.html"
    step = DomStep(name="s", action="dom", selector="#content", path=str(target))
    result = execute_action(session, step)

    assert isinstance(result, TextResult)
    assert "Captured" in result.text
    assert target.exists()
    assert target.read_text() == result.text


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


def test_parse_writes_decimal_and_date_rows(
    session: BrowserSession, tmp_path: object
) -> None:
    """A schema may declare types ``json.dumps`` cannot represent; the dump
    has to be JSON-mode or the whole flow dies on the write."""
    import json
    from pathlib import Path

    import yaml

    from llm_browser.models import ParseStep

    schema = Path(str(tmp_path)) / "invoice.yaml"
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

    target = Path(str(tmp_path)) / "rows.json"
    step = ParseStep(
        name="s",
        action="parse",
        selector="tr.row",
        schema_path=str(schema),
        path=str(target),
    )
    execute_action(session, step)
    assert json.loads(target.read_text()) == [{"total": "10.25", "due": "2024-03-01"}]


def test_an_unserializable_row_is_an_error_result_naming_the_path(
    session: BrowserSession, tmp_path: object
) -> None:
    """Caught where the write happens, not by a blanket `TypeError` catch in
    `execute_action`: writing the output is part of the step, a bug in some
    other action is not."""
    from pathlib import Path

    _rows_locator(session, [{"name": "Alice"}])

    target = Path(str(tmp_path)) / "rows.json"
    step = ReadStep(
        name="s",
        action="read",
        selector="tr",
        extract={"name": {"child_selector": "td", "attribute": "textContent"}},
        path=str(target),
    )
    result = execute_action(session, step)
    assert isinstance(result, actions.ParsedResult)

    unserializable = actions.ParsedResult(rows=[actions.ExtractedRow(name=object())])
    with pytest.raises(ValueError, match=f"cannot write rows to {target}"):
        actions._write_rows(str(target), unserializable)


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
