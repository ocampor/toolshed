"""Browser-free tests for the reporting half of the runner.

``scripts/validate.sh`` runs ``pytest -q`` without ``--real``, so this is the
only part of the package CI actually exercises — everything pure lives here.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from llm_browser_conformance import runner
from llm_browser_conformance.runner import (
    TEARDOWN_ROW,
    Result,
    as_json,
    cell,
    failed,
    format_table,
    notes,
    one_line,
    run_driver,
    run_scenario,
)
from llm_browser_conformance.scenario import Outcome, Section
from llm_browser_conformance.scenarios import ALL_SCENARIOS, select
from tests.fakes import FAKE_DRIVER, FAKE_SCENARIOS, fake_context


def row(
    scenario: str,
    driver: str,
    outcome: Outcome,
    detail: str = "",
    section: Section = Section.WAITS,
) -> Result:
    return Result(scenario, section, driver, outcome, 1.25, detail)


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (Outcome.PASS, False),
        (Outcome.XFAIL, False),
        (Outcome.SKIP, False),
        (Outcome.FAIL, True),
        (Outcome.XPASS, True),
    ],
)
def test_only_a_failure_or_a_closed_gap_fails_the_run(
    outcome: Outcome, expected: bool
) -> None:
    assert outcome.is_failure is expected
    assert failed([row("s", "d", outcome)]) is expected


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (Outcome.PASS, "pass 1.2s"),
        (Outcome.XFAIL, "xfail 1.2s"),
        (Outcome.SKIP, "skip"),
        (Outcome.FAIL, "FAIL"),
        (Outcome.XPASS, "XPASS"),
    ],
)
def test_cell_renders_each_outcome(outcome: Outcome, expected: str) -> None:
    assert cell(row("s", "d", outcome)) == expected


def test_a_missing_result_renders_as_not_applicable() -> None:
    assert cell(None) == "-"


def test_the_table_groups_by_section_and_marks_gaps() -> None:
    results = [
        row("wait attached", "patchright", Outcome.PASS),
        row("wait attached", "nodriver", Outcome.PASS),
        row("stealth thing", "nodriver", Outcome.PASS, section=Section.STEALTH),
    ]
    table = format_table(results, ["patchright", "nodriver"])
    lines = table.splitlines()
    assert lines[0].split() == ["patchright", "nodriver"]
    assert "[waits]" in lines
    assert "[stealth]" in lines
    # patchright has no stealth row at all, which is not a failure.
    stealth = next(line for line in lines if line.startswith("stealth thing"))
    assert stealth.split() == ["stealth", "thing", "-", "pass", "1.2s"]


def test_notes_group_one_reason_per_line() -> None:
    reason = "browser would not start"
    results = [
        row("a", "camoufox", Outcome.FAIL, reason),
        row("b", "camoufox", Outcome.FAIL, reason),
        row("c", "nodriver", Outcome.SKIP, "no chrome"),
        row("d", "patchright", Outcome.PASS, "a passing note nobody needs"),
    ]
    assert notes(results) == [
        "details:",
        f"camoufox     fail   2 scenarios: {reason}",
        "nodriver     skip   c: no chrome",
    ]


def test_notes_are_empty_when_everything_passed() -> None:
    assert notes([row("a", "patchright", Outcome.PASS)]) == []


def test_json_carries_every_row_and_the_verdict() -> None:
    results = [row("a", "patchright", Outcome.PASS), row("b", "nodriver", Outcome.FAIL)]
    payload = json.loads(as_json(results, ["patchright", "nodriver"], 1000))
    assert payload["ok"] is False
    assert payload["delay_ms"] == 1000
    assert payload["drivers"] == ["patchright", "nodriver"]
    assert {r["scenario"] for r in payload["results"]} == {"a", "b"}


def test_one_line_names_the_assertion_that_raised() -> None:
    expected, actual = "clicked", "header"
    try:
        assert expected == actual, "values differ"
    except AssertionError as error:
        message = one_line(error)
    assert message.startswith("values differ")
    assert "test_runner.py:" in message


def test_one_line_falls_back_to_the_exception_type() -> None:
    assert one_line(RuntimeError()) == "RuntimeError"


def test_select_filters_by_substring() -> None:
    assert select(()) is ALL_SCENARIOS
    names = [s.name for s in select(("iframe",))]
    assert names and all("iframe" in name for name in names)
    assert select(("no-such-scenario",)) == []


def test_run_scenario_maps_each_shape_to_a_verdict() -> None:
    ctx = fake_context()
    verdicts = {s.name: run_scenario(s, ctx).outcome for s in FAKE_SCENARIOS}
    assert verdicts == {
        "passes": Outcome.PASS,
        "notes": Outcome.PASS,
        "fails": Outcome.FAIL,
        "skips": Outcome.SKIP,
        "known gap": Outcome.XFAIL,
        "gap closed": Outcome.XPASS,
        "other driver only": Outcome.SKIP,
    }


def test_a_returned_note_reaches_the_report() -> None:
    scenario = next(s for s in FAKE_SCENARIOS if s.name == "notes")
    assert run_scenario(scenario, fake_context()).detail == "observed something"


@contextmanager
def session_that_fails_to_close() -> Iterator[Any]:
    yield None
    raise RuntimeError("There is no current event loop")


def test_a_teardown_error_gets_its_own_row_and_keeps_the_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression this guards: a browser that will not *stop* has already
    answered every question, so its column must survive."""
    monkeypatch.setattr(runner, "unavailable", lambda driver: None)
    monkeypatch.setattr(
        runner, "launched_session", lambda driver: session_that_fails_to_close()
    )
    results = run_driver(FAKE_DRIVER, "http://127.0.0.1:1", list(FAKE_SCENARIOS), 1000)
    teardown = [r for r in results if r.scenario == TEARDOWN_ROW]
    assert len(teardown) == 1
    assert teardown[0].outcome is Outcome.FAIL
    assert "no current event loop" in teardown[0].detail
    kept = {r.scenario for r in results if r.scenario != TEARDOWN_ROW}
    assert kept == {s.name for s in FAKE_SCENARIOS if s.applies_to(FAKE_DRIVER)}


@contextmanager
def session_that_fails_to_launch() -> Iterator[Any]:
    raise RuntimeError("Executable doesn't exist")
    yield None


def test_a_launch_error_marks_every_applicable_scenario(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "unavailable", lambda driver: None)
    monkeypatch.setattr(
        runner, "launched_session", lambda driver: session_that_fails_to_launch()
    )
    results = run_driver(FAKE_DRIVER, "http://127.0.0.1:1", list(FAKE_SCENARIOS), 1000)
    applicable = [s for s in FAKE_SCENARIOS if s.applies_to(FAKE_DRIVER)]
    assert len(results) == len(applicable)
    assert all(r.outcome is Outcome.FAIL for r in results)
    assert all(r.detail.startswith("launch: ") for r in results)


def test_an_unavailable_driver_skips_every_scenario(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "unavailable", lambda driver: "extra not installed")
    results = run_driver(FAKE_DRIVER, "http://127.0.0.1:1", list(FAKE_SCENARIOS), 1000)
    assert len(results) == len(FAKE_SCENARIOS)
    assert all(r.outcome is Outcome.SKIP for r in results)
