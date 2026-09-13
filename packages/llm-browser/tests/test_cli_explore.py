"""`llm-browser explore`: JSON on stdout, non-zero exit when nothing matched."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from llm_browser.cli import main
from llm_browser.explore_models import ExploreResult, Intent, Verdict
from llm_browser.session import BrowserSession
from llm_browser.survey_models import Hydration, Landmark, Survey

from tests.conftest import ExploringSession


@pytest.fixture
def cli_explore(
    exploring_session: ExploringSession, monkeypatch: pytest.MonkeyPatch
) -> ExploringSession:
    def build(
        rows: list[dict[str | None, str | None]], **canned: object
    ) -> BrowserSession:
        session = exploring_session(rows, **canned)
        monkeypatch.setattr("llm_browser.cli.build_session", lambda **kwargs: session)
        return session

    return build


def test_explore_outputs_the_count_and_the_sampled_rows(
    cli_explore: ExploringSession,
) -> None:
    cli_explore([{".label": "Alpha"}, {".label": "Beta"}], text="12345")

    result = CliRunner().invoke(
        main, ["explore", "--selector", ".row", "--extract", "label=.label"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["count"] == 2
    assert payload["sample"] == [{"label": "Alpha"}, {"label": "Beta"}]
    assert payload["empty_fields"] == []
    assert payload["text_chars"] == 10
    assert payload["verdict"] == "ok"


def test_explore_keeps_a_null_field_in_the_json_so_empty_fields_can_be_checked(
    cli_explore: ExploringSession,
) -> None:
    cli_explore([{".label": "Alpha", ".note": None}])

    result = CliRunner().invoke(
        main,
        [
            "explore",
            "--selector",
            ".row",
            "--extract",
            "label=.label",
            "--extract",
            "note=.note",
        ],
    )

    payload = json.loads(result.output)
    assert payload["sample"] == [{"label": "Alpha", "note": None}]
    assert payload["empty_fields"] == ["note"]


def test_explore_exits_non_zero_when_the_selector_matched_nothing(
    cli_explore: ExploringSession,
) -> None:
    cli_explore([])

    result = CliRunner().invoke(
        main, ["explore", "--selector", ".row", "--timeout", "0"]
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["count"] == 0
    assert payload["verdict"] == "missing"
    # `_output` drops nulls, so a missing selector has neither key at all.
    assert "first" not in payload and "appeared_after_ms" not in payload


def test_intent_click_on_one_clickable_match_exits_zero(
    cli_explore: ExploringSession,
) -> None:
    cli_explore([{".label": "Alpha"}])

    result = CliRunner().invoke(
        main, ["explore", "--selector", ".row", "--intent", "click"]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["verdict"] == "ok"


def test_intent_click_on_a_covered_match_exits_one(
    cli_explore: ExploringSession,
) -> None:
    """The read exits zero on the same element: only a click is refused."""
    cli_explore(
        [{".label": "Alpha"}],
        first={
            "clickable": False,
            "why_not": ["covered"],
            "covered_by": {"tag": "div", "text": "Cookies"},
        },
    )

    refused = CliRunner().invoke(
        main, ["explore", "--selector", ".row", "--intent", "click"]
    )
    read = CliRunner().invoke(main, ["explore", "--selector", ".row"])

    assert refused.exit_code == 1
    payload = json.loads(refused.output)
    assert payload["verdict"] == "not_actionable"
    assert payload["first"]["why_not"] == ["covered"]
    assert payload["first"]["covered_by"] == {"tag": "div", "text": "Cookies"}
    assert read.exit_code == 0, read.output


def test_intent_click_on_two_matches_exits_one(
    cli_explore: ExploringSession,
) -> None:
    cli_explore([{".label": "Alpha"}, {".label": "Beta"}])

    result = CliRunner().invoke(
        main, ["explore", "--selector", ".row", "--intent", "click"]
    )

    assert result.exit_code == 1
    assert json.loads(result.output)["verdict"] == "ambiguous"


def test_explore_rejects_an_extract_without_a_name(
    cli_explore: ExploringSession,
) -> None:
    cli_explore([{".label": "Alpha"}])

    result = CliRunner().invoke(
        main, ["explore", "--selector", ".row", "--extract", ".label"]
    )

    assert result.exit_code == 2
    assert "--extract expects name=spec" in result.output + result.stderr


def test_explore_rejects_the_same_extract_name_twice(
    cli_explore: ExploringSession,
) -> None:
    """A typo'd duplicate would otherwise discard the first spec in silence."""
    cli_explore([{".label": "Alpha"}])

    result = CliRunner().invoke(
        main,
        [
            "explore",
            "--selector",
            ".row",
            "--extract",
            "label=h3",
            "--extract",
            "label=h2",
        ],
    )

    assert result.exit_code == 2
    assert "--extract label given twice" in result.output + result.stderr


def test_sample_chars_cuts_each_field_of_the_sample(
    cli_explore: ExploringSession,
) -> None:
    cli_explore([{".label": "Alpha and then some"}])

    result = CliRunner().invoke(
        main,
        [
            "explore",
            "--selector",
            ".row",
            "--extract",
            "label=.label",
            "--sample-chars",
            "5",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["sample"] == [{"label": "Alpha"}]


@pytest.fixture
def cli_session(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """A session the CLI drives, so these tests are about the wiring only."""
    session = MagicMock(spec=BrowserSession)
    monkeypatch.setattr("llm_browser.cli.build_session", lambda **kwargs: session)
    return session


def explored(count: int, verdict: Verdict = Verdict.OK) -> ExploreResult:
    return ExploreResult(
        count=count, sample=[], empty_fields=[], text_chars=0, verdict=verdict
    )


def targets_file(tmp_path: Path, body: str) -> str:
    path = tmp_path / "targets.yaml"
    path.write_text(body)
    return str(path)


def test_a_targets_file_explores_them_all_in_the_order_written(
    cli_session: MagicMock, tmp_path: Path
) -> None:
    cli_session.explore_many.return_value = [explored(30), explored(1)]
    path = targets_file(
        tmp_path,
        "- selector: .row\n"
        "  extract:\n"
        "    title: a\n"
        "- selector: .morelink\n"
        "  intent: click\n",
    )

    result = CliRunner().invoke(main, ["explore", "--targets", path])

    assert result.exit_code == 0, result.output
    assert [answer["count"] for answer in json.loads(result.output)] == [30, 1]
    targets = cli_session.explore_many.call_args.args[0]
    assert [target.selector for target in targets] == [".row", ".morelink"]
    assert targets[1].intent is Intent.CLICK
    assert targets[0].extract["title"].child_selector == "a"


def test_one_bad_verdict_in_a_batch_is_a_non_zero_exit(
    cli_session: MagicMock, tmp_path: Path
) -> None:
    """The shell's question is "can I write these steps", and one no is a no."""
    cli_session.explore_many.return_value = [
        explored(1),
        explored(0, Verdict.MISSING),
    ]
    path = targets_file(tmp_path, "- selector: .row\n- selector: .gone\n")

    result = CliRunner().invoke(main, ["explore", "--targets", path])

    assert result.exit_code == 1, result.output


@pytest.mark.parametrize("both", [False, True])
def test_explore_takes_one_selector_or_one_file(tmp_path: Path, both: bool) -> None:
    path = targets_file(tmp_path, "- selector: .row\n")
    arguments = ["--selector", ".row", "--targets", path] if both else []

    result = CliRunner().invoke(main, ["explore", *arguments])

    assert result.exit_code == 2, result.output
    assert "exactly one of --selector or --targets" in result.output


def test_a_targets_file_that_is_not_a_list_is_a_usage_error(tmp_path: Path) -> None:
    path = targets_file(tmp_path, "selector: .row\n")

    result = CliRunner().invoke(main, ["explore", "--targets", path])

    assert result.exit_code == 2, result.output
    assert "expects a list" in result.output


def test_survey_outputs_what_the_page_is_made_of(cli_session: MagicMock) -> None:
    cli_session.survey.return_value = Survey(
        title="Missions",
        url="https://example.com",
        hydration=Hydration(since_navigation_ms=900, ready_state="complete"),
        landmarks=[Landmark(selector='[data-testid="grid"]', tag="main", count=1)],
    )

    result = CliRunner().invoke(main, ["survey", "--max-items", "10"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["landmarks"][0]["selector"] == '[data-testid="grid"]'
    assert payload["hydration"]["ready_state"] == "complete"
    assert cli_session.survey.call_args.kwargs == {"max_items": 10}


@pytest.mark.parametrize("option", [["--extract", "title=h3"], ["--intent", "click"]])
def test_a_flag_meant_for_one_selector_is_not_silently_ignored(
    tmp_path: Path, option: list[str]
) -> None:
    """A targets file carries its own intent and extract per entry."""
    path = targets_file(tmp_path, "- selector: .row\n")

    result = CliRunner().invoke(main, ["explore", "--targets", path, *option])

    assert result.exit_code == 2, result.output
    assert "per target inside --targets" in result.output
