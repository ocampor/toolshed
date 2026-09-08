"""Tests for running flows without touching disk: `load_flow_text`,
`run_flow` on a Flow model, in-memory step outputs, secret redaction."""

import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from llm_browser.flows import load_flow_text, run_flow
from llm_browser.models import Flow, FlowError, FlowSuccess, RunFlowStep
from llm_browser.redact import redact_secrets
from llm_browser.session import BrowserSession

CHILD_YAML = """
steps:
  - name: c1
    action: click
    selector: "#child"
"""


def _flow_yaml(steps: list[dict[str, Any]], **extra: Any) -> str:
    return yaml.dump({"steps": steps, **extra})


def _mock_session(tmp_path: Path) -> MagicMock:
    from llm_browser.behavior import Behavior

    session = MagicMock(spec=BrowserSession)
    session.session_dir = tmp_path
    session.behavior = Behavior.off()
    session._behavior_runtime = session.behavior.runtime()
    session.capture = "screenshot"
    session.driver = MagicMock()
    session.get_page.return_value = MagicMock()
    session.take_screenshot.return_value = tmp_path / "screenshot.png"
    session.element_exists.return_value = True
    locator = MagicMock()
    locator.count.return_value = 1
    session.find.return_value = locator
    session.parse_elements.return_value = [{"title": "hello"}]
    session.dom.return_value = "<p>hello</p>"
    return session


# --- load_flow_text ---


def test_load_flow_text_parses_steps() -> None:
    flow = load_flow_text(_flow_yaml([{"name": "s1", "action": "goto", "url": "u"}]))
    assert isinstance(flow, Flow)
    assert flow.steps[0].name == "s1"


def test_load_flow_text_resolves_subflow_via_loader() -> None:
    parent = _flow_yaml(
        [{"name": "child", "action": "run-flow", "flow": "registry://child"}]
    )
    flow = load_flow_text(parent, subflow_loader=lambda ref: CHILD_YAML)
    step = flow.steps[0]
    assert isinstance(step, RunFlowStep)
    assert step.subflow is not None
    assert step.subflow.steps[0].name == "c1"


def test_load_flow_text_loader_receives_reference() -> None:
    seen: list[str] = []

    def loader(ref: str) -> str:
        seen.append(ref)
        return CHILD_YAML

    load_flow_text(
        _flow_yaml([{"name": "c", "action": "run-flow", "flow": "shared/login"}]),
        subflow_loader=loader,
    )
    assert seen == ["shared/login"]


def test_load_flow_text_prefers_existing_file(tmp_path: Path) -> None:
    """An existing path wins over the loader, so a text flow can still
    reference on-disk children."""
    child = tmp_path / "child.yaml"
    child.write_text(CHILD_YAML)
    flow = load_flow_text(
        _flow_yaml([{"name": "c", "action": "run-flow", "flow": str(child)}]),
        subflow_loader=lambda ref: pytest.fail("loader should not be called"),
    )
    step = flow.steps[0]
    assert isinstance(step, RunFlowStep)
    assert step.subflow is not None


def test_load_flow_text_without_loader_rejects_subflow() -> None:
    with pytest.raises(ValueError, match="subflow_loader"):
        load_flow_text(
            _flow_yaml([{"name": "c", "action": "run-flow", "flow": "registry://x"}])
        )


def test_load_flow_text_rejects_nested_subflow() -> None:
    nested = _flow_yaml([{"name": "n", "action": "run-flow", "flow": "deeper"}])
    with pytest.raises(ValueError, match="nested sub-flows"):
        load_flow_text(
            _flow_yaml([{"name": "c", "action": "run-flow", "flow": "child"}]),
            subflow_loader=lambda ref: nested,
        )


def test_load_flow_text_expands_selector_refs() -> None:
    flow = load_flow_text(
        _flow_yaml([{"name": "s", "action": "click", "ref": "ui.button"}]),
        selector_map={"ui.button": {"id": "the-button"}},
    )
    assert "the-button" in str(flow.steps[0])


# --- run_flow on a Flow model ---


def test_run_flow_accepts_flow_model(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    flow = load_flow_text(
        _flow_yaml([{"name": "s", "action": "click", "selector": "#a"}])
    )
    result = run_flow(session, flow, {})
    assert isinstance(result, FlowSuccess)
    assert result.step == "s"


def test_run_flow_model_failure_hint_has_empty_path(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    session.find.side_effect = TimeoutError("element missing")
    flow = load_flow_text(
        _flow_yaml([{"name": "boom", "action": "click", "selector": "#a"}])
    )
    result = run_flow(session, flow, {"k": "v"})
    assert isinstance(result, FlowError)
    assert result.retry_hint is not None
    assert result.retry_hint.flow_path == ""
    assert result.retry_hint.failed_step == "boom"


def test_run_flow_model_runs_subflow(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    flow = load_flow_text(
        _flow_yaml([{"name": "c", "action": "run-flow", "flow": "child"}]),
        subflow_loader=lambda ref: CHILD_YAML,
    )
    assert isinstance(run_flow(session, flow, {}), FlowSuccess)
    assert session.find.call_count == 1


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
    tmp_path: Path, step: dict[str, Any], key: str, expected: object
) -> None:
    session = _mock_session(tmp_path)
    result = run_flow(session, load_flow_text(_flow_yaml([step])), {})
    assert isinstance(result, FlowSuccess)
    assert result.outputs == {key: expected}


def test_outputs_kept_when_path_also_writes_a_file(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    out = tmp_path / "rows.json"
    flow = load_flow_text(_flow_yaml([_read_step(path=str(out))]))
    result = run_flow(session, flow, {})
    assert isinstance(result, FlowSuccess)
    assert result.outputs == {"grab": [{"title": "hello"}]}
    assert out.exists()


def test_outputs_from_parse_step(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    session.parse_elements.return_value = [{"title": "hello", "stars": "3"}]
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
    result = run_flow(session, flow, {})
    assert isinstance(result, FlowSuccess)
    assert result.outputs == {"rows": [{"title": "hello", "stars": 3}]}


def test_outputs_exclude_screenshots(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    flow = load_flow_text(_flow_yaml([{"name": "shot", "action": "screenshot"}]))
    result = run_flow(session, flow, {})
    assert isinstance(result, FlowSuccess)
    assert result.outputs == {}


def test_outputs_from_subflow_are_qualified(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    child = _flow_yaml([_dom_step()])
    flow = load_flow_text(
        _flow_yaml([{"name": "inner", "action": "run-flow", "flow": "child"}]),
        subflow_loader=lambda ref: child,
    )
    result = run_flow(session, flow, {})
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
    from llm_browser.actions import ErrorResult

    result = ErrorResult(error="ValueError", message="bad s3cret", step_name="s")
    redacted = redact_secrets(result, ["s3cret"])
    assert isinstance(redacted, ErrorResult)
    assert redacted.message == "bad ***"


def test_redact_hides_secret_in_retry_hint_and_error(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    session.find.side_effect = ValueError("login failed for s3cret")
    flow = load_flow_text(
        _flow_yaml(
            [{"name": "login", "action": "fill", "selector": "#p", "value": "x"}]
        )
    )
    result = run_flow(session, flow, {"password": "s3cret"}, redact=["s3cret"])
    assert isinstance(result, FlowError)
    assert result.retry_hint is not None
    assert result.retry_hint.data == {"password": "***"}
    assert "s3cret" not in result.retry_hint.error
    assert "s3cret" not in str(result.data)


def test_redact_hides_secret_in_outputs(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    session.dom.return_value = "<input value='s3cret'>"
    flow = load_flow_text(_flow_yaml([_dom_step()]))
    result = run_flow(session, flow, {}, redact=["s3cret"])
    assert isinstance(result, FlowSuccess)
    assert result.outputs == {"snap": "<input value='***'>"}


def test_redact_scrubs_log_records(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    session = _mock_session(tmp_path)
    logger = logging.getLogger("llm_browser")

    def log_and_return(*args: object, **kwargs: object) -> str:
        logger.warning("dom for %s", "s3cret")
        return "<p>ok</p>"

    session.dom.side_effect = log_and_return
    flow = load_flow_text(_flow_yaml([_dom_step()]))
    with caplog.at_level(logging.WARNING, logger="llm_browser"):
        run_flow(session, flow, {}, redact=["s3cret"])
    assert "s3cret" not in caplog.text
    assert "***" in caplog.text


def test_redaction_filter_is_removed_after_the_run(tmp_path: Path) -> None:
    session = _mock_session(tmp_path)
    flow = load_flow_text(_flow_yaml([_dom_step()]))
    run_flow(session, flow, {}, redact=["s3cret"])
    assert logging.getLogger("llm_browser").filters == []
