"""Tests for stage two (`load_flow_text`), `run_flow`, outputs, redaction."""

import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from llm_browser.flows import load_flow_document, load_flow_text, run_flow
from llm_browser.models import Flow, FlowError, FlowSuccess
from llm_browser.redact import redact_secrets
from llm_browser.results import BytesResult
from tests.conftest import PNG

CHILD = {"steps": [{"name": "c1", "action": "click", "selector": "#child"}]}


def _flow_yaml(steps: list[dict[str, Any]], **extra: Any) -> str:
    return yaml.dump({"steps": steps, **extra})


def _run_flow_step(child: dict[str, Any], name: str = "c") -> dict[str, Any]:
    return {"name": name, "action": "run-flow", "flow": child}


# --- load_flow_text ---


def test_load_flow_text_parses_steps() -> None:
    flow = load_flow_text(_flow_yaml([{"name": "s1", "action": "goto", "url": "u"}]))
    assert isinstance(flow, Flow)
    assert flow.steps[0].name == "s1"


def test_load_flow_document_expands_selector_refs() -> None:
    flow = load_flow_document(
        {"steps": [{"name": "s", "action": "click", "ref": "ui.button"}]},
        selector_map={"ui.button": {"id": "the-button"}},
    )
    assert "the-button" in str(flow.steps[0])


def test_load_flow_text_rejects_an_unresolved_reference() -> None:
    with pytest.raises(ValueError, match="unresolved sub-flow child"):
        load_flow_text(
            _flow_yaml([{"name": "c", "action": "run-flow", "flow": "child"}])
        )


# --- run_flow on a Flow model ---


def test_run_flow_accepts_flow_model(mock_session: MagicMock) -> None:
    flow = load_flow_text(
        _flow_yaml([{"name": "s", "action": "click", "selector": "#a"}])
    )
    result = run_flow(mock_session, flow, {})
    assert isinstance(result, FlowSuccess)
    assert result.step == "s"


def test_run_flow_model_failure_hint_has_empty_path(mock_session: MagicMock) -> None:
    mock_session.click.side_effect = TimeoutError("element missing")
    flow = load_flow_text(
        _flow_yaml([{"name": "boom", "action": "click", "selector": "#a"}])
    )
    result = run_flow(mock_session, flow, {"k": "v"})
    assert isinstance(result, FlowError)
    assert result.retry_hint is not None
    assert result.retry_hint.flow_path == ""
    assert result.retry_hint.failed_step == "boom"


def test_run_flow_model_runs_subflow(mock_session: MagicMock) -> None:
    flow = load_flow_text(_flow_yaml([_run_flow_step(CHILD)]))
    assert isinstance(run_flow(mock_session, flow, {}), FlowSuccess)
    assert mock_session.click.call_count == 1


# --- outputs ---


def _read_step(**extra: Any) -> dict[str, Any]:
    return {
        "name": "grab",
        "action": "read",
        "selector": ".row",
        "extract": {"title": {"child_selector": "h1"}},
        **extra,
    }


def _dom_step(**extra: Any) -> dict[str, Any]:
    return {"name": "snap", "action": "dom", "selector": "#main", **extra}


@pytest.mark.parametrize(
    "step, key, expected",
    [
        (_read_step(), "grab", [{"title": "hello"}]),
        (_dom_step(), "snap", "<p>hello</p>"),
    ],
)
def test_outputs_collected_without_path(
    mock_session: MagicMock,
    step: dict[str, Any],
    key: str,
    expected: object,
) -> None:
    result = run_flow(mock_session, load_flow_text(_flow_yaml([step])), {})
    assert isinstance(result, FlowSuccess)
    assert result.outputs == {key: expected}


def test_a_step_path_writes_nothing_and_keeps_the_output(
    tmp_path: Path,
    mock_session: MagicMock,
) -> None:
    """``path:`` is a CLI instruction; ``run_flow`` returns the rows and
    leaves the filesystem alone."""
    out = tmp_path / "rows.json"
    flow = load_flow_text(_flow_yaml([_read_step(path=str(out))]))
    result = run_flow(mock_session, flow, {})
    assert isinstance(result, FlowSuccess)
    assert result.outputs == {"grab": [{"title": "hello"}]}
    assert not out.exists()


def test_outputs_from_parse_step(tmp_path: Path, mock_session: MagicMock) -> None:
    mock_session.parse_elements.return_value = [{"title": "hello", "stars": "3"}]
    schema = tmp_path / "schema.yaml"
    schema.write_text(
        yaml.dump(
            {
                "name": "Row",
                "fields": {
                    "title": {"type": "str", "child_selector": "h1"},
                    "stars": {"type": "int", "child_selector": ".s"},
                },
            }
        )
    )
    flow = load_flow_text(
        _flow_yaml(
            [
                {
                    "name": "rows",
                    "action": "parse",
                    "selector": ".row",
                    "schema_path": str(schema),
                }
            ]
        )
    )
    result = run_flow(mock_session, flow, {})
    assert isinstance(result, FlowSuccess)
    assert result.outputs == {"rows": [{"title": "hello", "stars": 3}]}


def test_screenshot_output_is_bytes(mock_session: MagicMock) -> None:
    flow = load_flow_text(_flow_yaml([{"name": "shot", "action": "screenshot"}]))
    result = run_flow(mock_session, flow, {})
    assert isinstance(result, FlowSuccess)
    shot = result.outputs["shot"]
    assert isinstance(shot, BytesResult)
    assert shot.content == PNG
    assert shot.media_type == "image/png"


def test_download_output_is_bytes(mock_session: MagicMock) -> None:
    mock_session.download_file.return_value = BytesResult(
        name="report.csv", content=b"a,b\n", media_type="text/csv"
    )
    flow = load_flow_text(
        _flow_yaml([{"name": "grab", "action": "download", "selector": "#dl"}])
    )
    result = run_flow(mock_session, flow, {})
    assert isinstance(result, FlowSuccess)
    assert result.outputs["grab"] == mock_session.download_file.return_value


def test_outputs_from_subflow_are_qualified(mock_session: MagicMock) -> None:
    flow = load_flow_text(
        _flow_yaml([_run_flow_step({"steps": [_dom_step()]}, name="inner")])
    )
    result = run_flow(mock_session, flow, {})
    assert isinstance(result, FlowSuccess)
    assert result.outputs == {"inner/snap": "<p>hello</p>"}


# --- redaction ---


@pytest.mark.parametrize(
    "value, expected",
    [
        ("token=s3cret", "token=***"),
        (["s3cret", 1], ["***", 1]),
        ({"pw": "s3cret"}, {"pw": "***"}),
        ({"a": {"b": ["s3cret"]}}, {"a": {"b": ["***"]}}),
        (None, None),
        (7, 7),
    ],
)
def test_redact_secrets_walks_values(value: object, expected: object) -> None:
    assert redact_secrets(value, ["s3cret"]) == expected


def test_redact_secrets_ignores_empty_secret_list() -> None:
    assert redact_secrets("s3cret", []) == "s3cret"


def test_redact_secrets_preserves_model_type() -> None:
    from llm_browser.results import ErrorResult

    result = ErrorResult(error="ValueError", message="bad s3cret", step_name="s")
    redacted = redact_secrets(result, ["s3cret"])
    assert isinstance(redacted, ErrorResult)
    assert redacted.message == "bad ***"


def test_redact_hides_secret_in_retry_hint_and_error(mock_session: MagicMock) -> None:
    mock_session.fill.side_effect = ValueError("login failed for s3cret")
    flow = load_flow_text(
        _flow_yaml(
            [{"name": "login", "action": "fill", "selector": "#p", "value": "x"}]
        )
    )
    result = run_flow(mock_session, flow, {"password": "s3cret"}, redact=["s3cret"])
    assert isinstance(result, FlowError)
    assert result.retry_hint is not None
    assert result.retry_hint.data == {"password": "***"}
    assert "s3cret" not in result.retry_hint.error
    assert "s3cret" not in str(result.data)


def test_redact_hides_secret_in_outputs(mock_session: MagicMock) -> None:
    mock_session.dom.return_value = "<input value='s3cret'>"
    flow = load_flow_text(_flow_yaml([_dom_step()]))
    result = run_flow(mock_session, flow, {}, redact=["s3cret"])
    assert isinstance(result, FlowSuccess)
    assert result.outputs == {"snap": "<input value='***'>"}


def test_redact_scrubs_log_records(
    mock_session: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("llm_browser")

    def log_and_return(*args: object, **kwargs: object) -> str:
        logger.warning("dom for %s", "s3cret")
        return "<p>ok</p>"

    mock_session.dom.side_effect = log_and_return
    flow = load_flow_text(_flow_yaml([_dom_step()]))
    with caplog.at_level(logging.WARNING, logger="llm_browser"):
        run_flow(mock_session, flow, {}, redact=["s3cret"])
    assert "s3cret" not in caplog.text
    assert "***" in caplog.text


def test_redaction_filter_is_removed_after_the_run(mock_session: MagicMock) -> None:
    flow = load_flow_text(_flow_yaml([_dom_step()]))
    run_flow(mock_session, flow, {}, redact=["s3cret"])
    assert logging.getLogger("llm_browser").filters == []
