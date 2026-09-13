"""Tests for BrowserSession state file lifecycle."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from llm_browser.chrome import is_process_alive
from llm_browser.drivers.base import Driver
from llm_browser.models import Intent, SessionInfo, Stability, Verdict
from llm_browser.parse import ExtractField
from llm_browser.session import BrowserSession

from tests.conftest import ExploringSession


def test_save_and_load_state(tmp_path: Path) -> None:
    session = BrowserSession(state_dir=tmp_path)
    info = SessionInfo(
        pid=9999, cdp_url="ws://127.0.0.1:9222/devtools", user_data_dir="/tmp/ud"
    )
    session._ensure_dirs()
    session.state.save(info)

    loaded = session.state.load()
    assert loaded is not None
    assert loaded.pid == 9999
    assert loaded.cdp_url == "ws://127.0.0.1:9222/devtools"


def test_load_state_missing(tmp_path: Path) -> None:
    session = BrowserSession(state_dir=tmp_path)
    assert session.state.load() is None


def test_clear_state(tmp_path: Path) -> None:
    session = BrowserSession(state_dir=tmp_path)
    info = SessionInfo(pid=9999, cdp_url="ws://localhost:9222", user_data_dir="/tmp/ud")
    session._ensure_dirs()
    session.state.save(info)
    assert session.state.load() is not None

    session.state.clear()
    assert session.state.load() is None


def test_clear_state_noop_when_missing(tmp_path: Path) -> None:
    session = BrowserSession(state_dir=tmp_path)
    session.state.clear()  # should not raise


def test_status_closed_no_state(tmp_path: Path) -> None:
    session = BrowserSession(state_dir=tmp_path)
    result = session.status()
    assert result.status == "closed"
    assert result.cdp_url is None


def test_session_dir_uses_session_id(tmp_path: Path) -> None:
    session = BrowserSession(session_id="sat", state_dir=tmp_path)
    assert session.session_dir == tmp_path / "sessions" / "sat"


def test_default_session_id(tmp_path: Path) -> None:
    session = BrowserSession(state_dir=tmp_path)
    assert session.session_dir == tmp_path / "sessions" / "default"


def testis_process_alive_current_pid() -> None:
    import os

    assert is_process_alive(os.getpid()) is True


def testis_process_alive_nonexistent() -> None:
    # PID 2^30 is extremely unlikely to exist
    assert is_process_alive(1 << 30) is False


# --- executable_path ---


def test_executable_path_threaded_to_driver(tmp_path: Path) -> None:
    from tests.test_attach import AttachStubDriver

    from llm_browser.drivers.base import DriverHandle

    driver = AttachStubDriver()
    captured: dict[str, object] = {}

    def capturing_launch(
        user_data_dir: Path,
        url: str | None,
        headed: bool,
        executable_path: str | None = None,
    ) -> DriverHandle:
        captured["executable_path"] = executable_path
        return DriverHandle(driver=driver.name, user_data_dir=str(user_data_dir), pid=1)

    driver.launch = capturing_launch  # type: ignore[method-assign]
    session = BrowserSession(
        state_dir=tmp_path,
        driver=driver,
        executable_path="/usr/bin/chromium",
    )
    session.launch(url=None, headed=False)
    assert captured["executable_path"] == "/usr/bin/chromium"


# --- element_exists ---


def _session_with_mock_driver(tmp_path: Path) -> BrowserSession:
    session = BrowserSession(state_dir=tmp_path)
    session.driver = MagicMock()
    session._page = MagicMock()
    return session


def test_element_exists_is_true_once_the_element_attaches(tmp_path: Path) -> None:
    session = _session_with_mock_driver(tmp_path)
    session.driver.count.return_value = 1
    assert session.element_exists("#out") is True


def test_element_exists_is_false_when_nothing_ever_matches(tmp_path: Path) -> None:
    session = _session_with_mock_driver(tmp_path)
    session.driver.count.return_value = 0
    assert session.element_exists("#out", timeout=0) is False


def test_element_exists_propagates_a_driver_error(tmp_path: Path) -> None:
    """A CDP failure is not "not yet": only a timeout reads as False."""
    session = _session_with_mock_driver(tmp_path)
    session.driver.count.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        session.element_exists("#out")


def test_screenshot_bytes_returns_driver_bytes(tmp_path: Path) -> None:
    driver = MagicMock(spec=Driver)
    driver.screenshot_bytes.return_value = b"png-bytes"
    session = BrowserSession(state_dir=tmp_path, driver=driver)
    session._page = MagicMock()

    assert session.screenshot_bytes() == b"png-bytes"
    driver.screenshot_bytes.assert_called_once_with(session._page)


def test_screenshot_bytes_writes_nothing_to_session_dir(tmp_path: Path) -> None:
    driver = MagicMock(spec=Driver)
    driver.screenshot_bytes.return_value = b"png-bytes"
    session = BrowserSession(state_dir=tmp_path, driver=driver)
    session._page = MagicMock()

    session.screenshot_bytes()
    assert not session.session_dir.exists()


# --- explore ---

LABELLED_ROWS: list[dict[str | None, str | None]] = [
    {".label": "Alpha", ".note": None},
    {".label": "Beta", ".note": ""},
    {".label": "Gamma", ".note": None},
    {".label": "Delta", ".note": None},
]

LABEL_AND_NOTE = {
    "label": ExtractField(child_selector=".label"),
    "note": ExtractField(child_selector=".note"),
}


def test_explore_counts_every_match_but_samples_only_the_first_few(
    exploring_session: ExploringSession,
) -> None:
    session = exploring_session(LABELLED_ROWS)

    result = session.explore(".row", extract=LABEL_AND_NOTE, sample=2)

    assert result.count == 4
    assert result.sample == [
        {"label": "Alpha", "note": None},
        {"label": "Beta", "note": ""},
    ]


def test_explore_names_the_fields_no_sampled_row_filled_in(
    exploring_session: ExploringSession,
) -> None:
    session = exploring_session(LABELLED_ROWS)

    result = session.explore(".row", extract=LABEL_AND_NOTE)

    assert result.empty_fields == ["note"]


def test_explore_reads_the_rows_own_text_when_no_extract_is_given(
    exploring_session: ExploringSession,
) -> None:
    session = exploring_session([{None: "Alpha"}, {None: "Beta"}])

    result = session.explore(".row")

    assert result.sample == [{"text": "Alpha"}, {"text": "Beta"}]
    assert result.empty_fields == []


def test_explore_sums_the_rendered_text_of_the_sampled_elements(
    exploring_session: ExploringSession,
) -> None:
    session = exploring_session(LABELLED_ROWS, text="12345")

    result = session.explore(".row", sample=3)

    assert result.text_chars == 15


def test_explore_names_a_child_selector_that_matches_no_row(
    exploring_session: ExploringSession,
) -> None:
    """The read of an absent child is a miss, not a wait — see
    `test_read_field_of_a_missing_child_is_none` for the driver side."""
    session = exploring_session(LABELLED_ROWS)

    result = session.explore(
        ".row",
        extract={"absent": ExtractField(child_selector=".nothing-matches-this")},
        sample=2,
    )

    assert result.sample == [{"absent": None}, {"absent": None}]
    assert result.empty_fields == ["absent"]


def test_explore_reports_a_selector_that_never_arrives_as_a_count_of_zero(
    exploring_session: ExploringSession,
) -> None:
    session = exploring_session([])

    result = session.explore(".row", timeout_ms=0)

    assert result.count == 0
    assert result.sample == []
    assert result.text_chars == 0


# --- explore: the first match, the verdict, the candidates ---

ONE_ROW: list[dict[str | None, str | None]] = [{".label": "Alpha"}]
TWO_ROWS: list[dict[str | None, str | None]] = [{".label": "Alpha"}, {".label": "Beta"}]

COVERED = {"clickable": False, "why_not": ["covered"]}
DISABLED = {"clickable": False, "enabled": False, "why_not": ["disabled"]}


@pytest.mark.parametrize(
    ("intent", "rows", "first", "expected"),
    [
        (Intent.READ, TWO_ROWS, {}, Verdict.OK),
        (Intent.READ, [], {}, Verdict.MISSING),
        (Intent.WAIT, ONE_ROW, COVERED, Verdict.OK),
        (Intent.WAIT, TWO_ROWS, {}, Verdict.AMBIGUOUS),
        (Intent.CLICK, ONE_ROW, {}, Verdict.OK),
        (Intent.CLICK, ONE_ROW, COVERED, Verdict.NOT_ACTIONABLE),
        (Intent.CLICK, TWO_ROWS, {}, Verdict.AMBIGUOUS),
        (Intent.FILL, ONE_ROW, COVERED, Verdict.OK),
        (Intent.FILL, ONE_ROW, DISABLED, Verdict.NOT_ACTIONABLE),
        (Intent.FILL, ONE_ROW, {"visible": False}, Verdict.NOT_ACTIONABLE),
    ],
)
def test_the_verdict_answers_the_intent(
    intent: Intent,
    rows: list[dict[str | None, str | None]],
    first: dict[str, object],
    expected: Verdict,
    exploring_session: ExploringSession,
) -> None:
    """A `read` is happy with any number of matches; a covered element is
    still fine to wait for or to fill, and only a click cares."""
    session = exploring_session(rows, first=first)

    assert session.explore(".row", timeout_ms=0, intent=intent).verdict == expected


def test_explore_reads_the_first_match_once(
    exploring_session: ExploringSession,
) -> None:
    session = exploring_session(TWO_ROWS, first={"text": "Alpha", "href": "/alpha"})

    result = session.explore(".row")

    assert result.first is not None
    assert (result.first.text, result.first.href) == ("Alpha", "/alpha")
    assert session.driver.evaluate.call_count == 1


def test_a_candidate_has_to_match_exactly_one_element(
    exploring_session: ExploringSession,
) -> None:
    """The proposals come off the first match's own attributes, so a unique
    match is that element; one that matches twice names something else too."""
    session = exploring_session(
        ONE_ROW,
        candidates=["#alpha", '[aria-label="Go"]'],
        matches={"#alpha": 1, '[aria-label="Go"]': 2},
    )

    assert session.explore(".row").candidates == ["#alpha"]


def test_only_three_candidates_are_kept(exploring_session: ExploringSession) -> None:
    proposals = ["#a", "#b", "#c", "#d"]
    session = exploring_session(ONE_ROW, candidates=proposals)

    assert session.explore(".row").candidates == proposals[:3]


def test_a_candidate_no_driver_can_parse_is_not_one(
    exploring_session: ExploringSession,
) -> None:
    session = exploring_session(ONE_ROW, candidates=["role=button[name=Go]"])
    resolve = session.driver.resolve.side_effect

    def refuse_the_role_engine(page: object, selector: str) -> object:
        if selector.startswith("role="):
            raise ValueError("unknown engine: role")
        return resolve(page, selector)

    session.driver.resolve.side_effect = refuse_the_role_engine

    assert session.explore(".row").candidates == []


def test_a_selector_that_never_arrives_has_no_first_match_and_no_timing(
    exploring_session: ExploringSession,
) -> None:
    result = exploring_session([]).explore(".row", timeout_ms=0, intent=Intent.CLICK)

    assert (result.first, result.appeared_after_ms) == (None, None)
    assert result.verdict == Verdict.MISSING


def test_explore_times_how_long_the_first_match_took(
    exploring_session: ExploringSession,
) -> None:
    result = exploring_session(ONE_ROW).explore(".row")

    assert result.appeared_after_ms is not None and result.appeared_after_ms >= 0


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ('[data-testid="row"]', Stability.DATA_TESTID),
        ('[aria-label="Search"]', Stability.ARIA),
        ("role=button[name=Go]", Stability.ARIA),
        ("#searchInput", Stability.ID),
        (".css-1x2y3z button", Stability.CLASS_HASH),
        (".grid-cols-12", Stability.OTHER),
        ("ul > li:nth-child(2)", Stability.POSITIONAL),
        ("tr.athing", Stability.OTHER),
    ],
)
def test_stability_reads_the_selector_a_redeploy_would_break(
    selector: str, expected: Stability, exploring_session: ExploringSession
) -> None:
    session = exploring_session(ONE_ROW)

    assert session.explore(selector).stability == expected
