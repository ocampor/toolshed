"""``--failed``: what the last run said, and what that makes worth rerunning."""

import json
from pathlib import Path

import pytest
from click.testing import Result as Result_

from llm_browser_conformance import history
from llm_browser_conformance.runner import Result
from llm_browser_conformance.scenario import Outcome, Scenario, Section
from tests.fakes import FAKE_SCENARIOS


def row(scenario: str, driver: str, outcome: Outcome) -> Result:
    return Result(scenario, Section.WAITS, driver, outcome, 1.0, "why")


def test_no_file_is_no_history(tmp_path: Path) -> None:
    assert history.load(tmp_path / "absent.json") == []


@pytest.mark.parametrize(
    ("content", "why"),
    [
        ("{not json", "malformed json"),
        (
            (
                '[{"scenario": "a", "section": "gone", "driver": "d", '
                '"outcome": "pass", "elapsed_s": 1.0}]'
            ),
            "a section this build dropped",
        ),
        (
            (
                '[{"scenario": "a", "section": "waits", "driver": "d", '
                '"outcome": "flaky", "elapsed_s": 1.0}]'
            ),
            "an outcome from a newer build",
        ),
        ('[{"scenario": "a", "driver": "d"}]', "a field that has since been added"),
        ('{"results": []}', "an object where a list used to be"),
    ],
)
def test_a_drifted_record_is_no_history(tmp_path: Path, content: str, why: str) -> None:
    """The file carries no version, and every run reads it — so a record this
    build cannot parse must never be why a run cannot happen."""
    path = tmp_path / "last.json"
    path.write_text(content)
    with pytest.warns(UserWarning, match="ignoring unreadable"):
        assert history.load(path) == [], why


def test_a_saved_run_reads_back_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "last.json"
    results = [row("a", "nodriver", Outcome.PASS), row("b", "camoufox", Outcome.FAIL)]
    history.save(results, path)
    assert history.load(path) == results
    assert json.loads(path.read_text())[0]["outcome"] == "pass"


@pytest.mark.parametrize(
    ("outcome", "rerun"),
    [
        (Outcome.FAIL, True),
        (Outcome.XFAIL, True),
        (Outcome.XPASS, False),
        (Outcome.PASS, False),
        (Outcome.SKIP, False),
    ],
)
def test_only_a_failure_or_a_known_gap_is_worth_rerunning(
    outcome: Outcome, rerun: bool
) -> None:
    scenario = FAKE_SCENARIOS[0]
    plan = history.rerun_plan(
        [row(scenario.name, "nodriver", outcome)], ["nodriver"], FAKE_SCENARIOS
    )
    assert (plan == {"nodriver": [scenario]}) is rerun


def test_each_driver_reruns_only_its_own_failures() -> None:
    first, second = FAKE_SCENARIOS[0], FAKE_SCENARIOS[1]
    previous = [
        row(first.name, "nodriver", Outcome.FAIL),
        row(second.name, "camoufox", Outcome.FAIL),
        row(second.name, "nodriver", Outcome.PASS),
    ]
    plan = history.rerun_plan(previous, ["nodriver", "camoufox"], FAKE_SCENARIOS)
    assert plan == {"nodriver": [first], "camoufox": [second]}


def test_a_driver_with_nothing_to_rerun_is_left_out() -> None:
    previous = [row(FAKE_SCENARIOS[0].name, "nodriver", Outcome.PASS)]
    assert history.rerun_plan(previous, ["nodriver"], FAKE_SCENARIOS) == {}


def test_a_rerun_keeps_the_cells_it_did_not_visit() -> None:
    """The record describes the whole suite, not the last handful of rows."""
    previous = [
        row("a", "nodriver", Outcome.FAIL),
        row("b", "nodriver", Outcome.PASS),
        row("a", "camoufox", Outcome.FAIL),
    ]
    fresh = [row("a", "nodriver", Outcome.PASS)]
    merged = history.merge(previous, fresh)
    assert {(r.scenario, r.driver): r.outcome for r in merged} == {
        ("a", "nodriver"): Outcome.PASS,
        ("b", "nodriver"): Outcome.PASS,
        ("a", "camoufox"): Outcome.FAIL,
    }


def test_a_scenario_no_longer_in_the_suite_is_not_rerun() -> None:
    gone: list[Scenario] = []
    assert (
        history.rerun_plan(
            [row("deleted", "nodriver", Outcome.FAIL)], ["nodriver"], gone
        )
        == {}
    )


# --- the CLI end of it ---


def invoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *args: str) -> "Result_":
    """Run the CLI with a throwaway working directory and no browsers."""
    from click.testing import CliRunner

    from llm_browser_conformance import cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "installed_drivers", lambda: ["fake"])
    return CliRunner().invoke(cli.main, args)


def test_failed_without_a_previous_run_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = invoke(tmp_path, monkeypatch, "--failed")
    assert result.exit_code == 2
    assert "run `llm-browser-check` first" in result.output


def test_failed_with_a_clean_previous_run_says_so_and_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history.save(
        [row(FAKE_SCENARIOS[0].name, "fake", Outcome.PASS)],
        tmp_path / history.HISTORY_FILE,
    )
    result = invoke(tmp_path, monkeypatch, "--failed")
    assert result.exit_code == 0
    assert "nothing failed in the last run" in result.output


def test_a_filtered_run_merges_into_the_record_it_did_not_cover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--only` and `--driver` produce partial results too, so replacing the
    record would drop the very failures `--failed` exists to find again."""
    from llm_browser_conformance import cli

    history.save(
        [row("a", "fake", Outcome.FAIL), row("elsewhere", "other", Outcome.FAIL)],
        tmp_path / history.HISTORY_FILE,
    )
    monkeypatch.setattr(
        cli, "run", lambda plan, delay: [row("a", "fake", Outcome.PASS)]
    )
    invoke(tmp_path, monkeypatch, "--only", "wait")
    recorded = history.load(tmp_path / history.HISTORY_FILE)
    assert {(r.scenario, r.driver): r.outcome for r in recorded} == {
        ("a", "fake"): Outcome.PASS,
        ("elsewhere", "other"): Outcome.FAIL,
    }
