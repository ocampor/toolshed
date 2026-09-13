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
        rows: list[dict[str | None, str | None]], text: str = ""
    ) -> BrowserSession:
        session = exploring_session(rows, text=text)
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
    assert json.loads(result.output) == {
        "count": 2,
        "sample": [{"label": "Alpha"}, {"label": "Beta"}],
        "empty_fields": [],
        "text_chars": 10,
    }


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
    assert json.loads(result.output)["count"] == 0


def test_explore_rejects_an_extract_without_a_name(
    cli_explore: ExploringSession,
) -> None:
    cli_explore([{".label": "Alpha"}])

    result = CliRunner().invoke(
        main, ["explore", "--selector", ".row", "--extract", ".label"]
    )

    assert result.exit_code == 2
    assert "--extract expects name=spec" in result.output + result.stderr
