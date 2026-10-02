"""Secrets a typed read or caller data turned into numbers and dates."""

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from llm_browser.flows import load_flow_text, run_flow
from llm_browser.models import FlowError, FlowSuccess, match_warning
from llm_browser.redact import RedactingFilter, redact_secrets
from llm_browser.results import AcceptedMatch, ExtractedRow, ExtractError, ParsedResult
from llm_browser.session import BrowserSession
from tests.extract_helpers import serve_rows

PAGE = {
    "dob": ("05/17/1990", {"type": "date"}),
    "born": ("17 May 1990", {"type": "date", "languages": ["en"]}),
    "pin": ("0418", {"type": "int"}),
    "amt": ("41.80", {"type": "float"}),
    "total": ("4,180.00", {"type": "float"}),
    "at": ("1990-05-17T08:00:00Z", {"type": "datetime"}),
}


@pytest.fixture
def session(tmp_path: Path) -> BrowserSession:
    s = BrowserSession(state_dir=tmp_path)
    s._page = MagicMock()
    return s


def read_flow_text(extract: dict[str, object]) -> str:
    step = {"name": "grab", "action": "read", "selector": "tr", "extract": extract}
    return yaml.dump({"steps": [step]})


@pytest.mark.parametrize(
    "value, secret, expected",
    [
        (4180, "4180", "***"),
        (4180, "4,180", "***"),
        (4180.0, "4180", "***"),
        (Decimal("4180"), "4180", "***"),
        (date(1990, 5, 17), "1990-05-17", "***"),
        (datetime(1990, 5, 17, 8, tzinfo=UTC), "1990-05-17", "***"),
        ([{"pin": 4180, "n": 7}], "4180", [{"pin": "***", "n": 7}]),
        (7, "4180", 7),
        (True, "True", True),
    ],
)
def test_redact_secrets_masks_typed_leaves(
    value: object, secret: str, expected: object
) -> None:
    assert redact_secrets(value, [secret]) == expected


def test_page_text_is_masked_before_a_typed_read(session: BrowserSession) -> None:
    serve_rows(session, [{name: text for name, (text, _) in PAGE.items()}])
    extract = {name: spec for name, (_, spec) in PAGE.items()}
    secrets = [text for text, _ in PAGE.values()]

    result = run_flow(
        session, load_flow_text(read_flow_text(extract)), {}, redact=secrets
    )

    assert isinstance(result, FlowSuccess), result
    assert result.outputs == {"grab": [None]}
    # A number with no digits left is an unmatched pattern, not an error.
    errors = {(e.field, e.input) for e in result.extract_errors}
    assert errors == {("dob", "***"), ("born", "***"), ("at", "***")}
    dumped = result.model_dump_json()
    assert not [s for s in [*secrets, "1990", "418", "41.8"] if s in dumped]
    assert session.secrets == ()


def test_a_failed_pass_item_is_masked(mock_session: MagicMock) -> None:
    mock_session.dom.side_effect = ["one", TimeoutError("never")]
    inner = [{"name": "grab", "action": "dom", "selector": "#p"}]
    step = {"name": "each", "action": "repeat", "as": "code", "over": "pins"}
    flow = {"params": ["pins"], "steps": [{**step, "on_error": "skip", "steps": inner}]}

    result = run_flow(
        mock_session,
        load_flow_text(yaml.dump(flow)),
        {"pins": [1111, 4180]},
        redact=["4180"],
    )

    assert isinstance(result, FlowSuccess | FlowError)
    assert result.iterations["each"].failed[0].item == "***"
    assert result.retry_hint is not None
    assert result.retry_hint.data == {"pins": ["***"]}


def test_run_flow_masks_rows_but_not_model_numbers(mock_session: MagicMock) -> None:
    error = ExtractError(step="grab", row=1, field="f", msg="x", input="y")
    accepted = AcceptedMatch(expected=2, found=1, picked=1)
    mock_session.parse_elements.return_value = [{"qty": 1}]
    mock_session.extract_errors = [error]
    mock_session.matching.return_value.__enter__.return_value = [accepted]
    flow = load_flow_text(read_flow_text({"qty": {"child_selector": "td"}}))

    result = run_flow(mock_session, flow, {}, redact=["1"])

    assert isinstance(result, FlowSuccess)
    assert result.outputs == {"grab": [{"qty": "***"}]}
    assert result.extract_errors == [error]
    assert result.warnings == [match_warning("grab", accepted)]


def test_extracted_row_extras_are_masked() -> None:
    parsed = ParsedResult(rows=[ExtractedRow(pin=4180)])
    assert redact_secrets(parsed, ["4180"]).rows[0].model_extra == {"pin": "***"}


def test_a_number_log_arg_is_masked() -> None:
    record = logging.LogRecord("t", logging.INFO, "", 0, "pin=%d", (4180,), None)
    RedactingFilter(["4180"]).filter(record)
    assert record.getMessage() == "pin=***"
