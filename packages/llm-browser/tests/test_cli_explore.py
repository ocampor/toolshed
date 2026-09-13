"""`llm-browser explore`: JSON on stdout, non-zero exit when nothing matched."""

import json

import pytest
from click.testing import CliRunner

from llm_browser.cli import main
from llm_browser.session import BrowserSession

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
