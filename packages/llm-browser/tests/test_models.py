"""Tests for Pydantic model serialization round-trips."""

import pytest
from pydantic import ValidationError

from llm_browser.behavior import Jitter
from llm_browser.html import SanitizeLevel
from llm_browser.models import (
    ClickStep,
    DomStep,
    EvalStep,
    Flow,
    FlowData,
    FlowError,
    FlowSuccess,
    GotoStep,
    ParseStep,
    ReadStep,
    ScrollStep,
    SessionInfo,
    TypeStep,
    validate_step,
)


def test_session_info_round_trip() -> None:
    info = SessionInfo(
        pid=1234, cdp_url="ws://127.0.0.1:9222/devtools", user_data_dir="/tmp/ud"
    )
    json_str = info.model_dump_json()
    restored = SessionInfo.model_validate_json(json_str)
    assert restored == info


def test_flow_error_round_trip() -> None:
    """The capture survives a JSON round trip as the bytes that went in, not
    as the base64 they were transported as."""
    shot = b"\x89PNG\r\n\x1a\n\x00binary\xff"
    result = FlowError(
        step="check", data='{"cp": "05330"}', screenshot=shot, dom="<p>hi</p>"
    )
    restored = FlowError.model_validate_json(result.model_dump_json())
    assert restored.step == "check"
    assert restored.data == '{"cp": "05330"}'
    assert restored.screenshot == shot
    assert restored.dom == "<p>hi</p>"


def test_flow_error_screenshot_is_base64_on_the_wire() -> None:
    import base64

    shot = b"\x89PNG\r\n\x1a\n\xff"
    dumped = FlowError(step="s", screenshot=shot).model_dump(mode="json")
    assert dumped["screenshot"] == base64.b64encode(shot).decode()


def test_flow_error_rejects_a_screenshot_that_is_not_base64() -> None:
    """The field used to hold a path; a caller still passing one is told so
    rather than quietly storing the filename as the image."""
    with pytest.raises(ValidationError):
        FlowError(step="check", screenshot="/tmp/s.png")


def test_flow_success_minimal() -> None:
    result = FlowSuccess(step="end")
    assert result.step == "end"


def test_flow_error_exclude_none() -> None:
    result = FlowError(step="boom")
    d = result.model_dump(exclude_none=True)
    assert "data" not in d
    assert "screenshot" not in d
    assert "retry_hint" not in d
    assert d["step"] == "boom"


def test_step_defaults() -> None:
    step = EvalStep(name="s1")
    assert step.fields == []
    assert step.when == []
    assert step.action is None
    assert step.optional is False


def test_step_discriminated_union() -> None:
    step = validate_step({"name": "s1", "action": "goto", "url": "https://example.com"})
    assert isinstance(step, GotoStep)
    assert step.action == "goto"
    assert step.url == "https://example.com"


@pytest.mark.parametrize(
    "raw, delta, times",
    [
        ({}, 600, 1),
        ({"delta": -300}, -300, 1),
        ({"delta": 500, "times": 4}, 500, 4),
    ],
)
def test_scroll_step_parsing(raw: dict[str, int], delta: int, times: int) -> None:
    step = validate_step({"name": "s", "action": "scroll", **raw})
    assert isinstance(step, ScrollStep)
    assert (step.delta, step.times) == (delta, times)
    assert step.pause == Jitter(min_ms=300, max_ms=1200)


def test_scroll_step_pause_parsed_as_jitter() -> None:
    step = validate_step(
        {"name": "s", "action": "scroll", "pause": {"min_ms": 50, "max_ms": 100}}
    )
    assert isinstance(step, ScrollStep)
    assert step.pause == Jitter(min_ms=50, max_ms=100)


def test_warm_site_flow_validates() -> None:
    """The shipped warm-up flow must stay loadable as flows evolve."""
    from pathlib import Path

    from tests.flow_helpers import load_flow_file

    flow_path = Path(__file__).resolve().parents[1] / "flows" / "warm-site.yml"
    flow = load_flow_file(flow_path)
    assert [s.action for s in flow.steps] == [
        "goto",
        "think",
        "scroll",
        "click",
        "think",
        "scroll",
    ]


def test_flow_round_trip() -> None:
    flow = Flow(
        steps=[EvalStep(name="s1", eval="1+1"), EvalStep(name="s2", optional=True)]
    )
    data = flow.model_dump()
    restored = Flow.model_validate(data)
    assert len(restored.steps) == 2
    assert restored.steps[0].name == "s1"
    assert restored.steps[1].optional is True


def test_flow_rejects_duplicate_step_names() -> None:
    with pytest.raises(ValueError, match=r"duplicate step names \['bar', 'foo'\]"):
        Flow(
            steps=[
                EvalStep(name="foo"),
                EvalStep(name="bar"),
                EvalStep(name="foo"),
                EvalStep(name="bar"),
            ]
        )


def test_flow_data_to_template_dict() -> None:
    data = FlowData.model_validate({"rfc": "XEXX", "cp": None})
    d = data.to_template_dict()
    assert d == {"rfc": "XEXX"}


def test_flow_validate_data_registered_param() -> None:
    flow = Flow(params=["rfc"], steps=[EvalStep(name="s1")])
    data = flow.validate_data({"rfc": "XEXX"})
    assert data.rfc == "XEXX"  # type: ignore[attr-defined]


def test_flow_validate_data_missing_required() -> None:
    flow = Flow(params=["rfc"], steps=[EvalStep(name="s1")])
    with pytest.raises(ValueError, match="Missing required param: rfc"):
        flow.validate_data({})


def test_flow_validate_data_registered_optional() -> None:
    flow = Flow(params=["cp"], steps=[EvalStep(name="s1")])
    data = flow.validate_data({})
    assert data.cp is None  # type: ignore[attr-defined]


def test_flow_validate_data_inline_param() -> None:
    flow = Flow(
        params=[{"custom": {"required": False, "default": "00000"}}],
        steps=[EvalStep(name="s1")],
    )
    data = flow.validate_data({})
    assert data.custom == "00000"  # type: ignore[attr-defined]


def test_flow_validate_data_mixed_params() -> None:
    flow = Flow(
        params=["rfc", {"region": {"required": False, "default": "MX"}}],
        steps=[EvalStep(name="s1")],
    )
    data = flow.validate_data({"rfc": "XEXX"})
    assert data.rfc == "XEXX"  # type: ignore[attr-defined]
    assert data.region == "MX"  # type: ignore[attr-defined]


def test_flow_validate_data_extra_keys_passed_through() -> None:
    flow = Flow(params=["rfc"], steps=[EvalStep(name="s1")])
    data = flow.validate_data({"rfc": "XEXX", "extra": "value"})
    assert data.extra == "value"  # type: ignore[attr-defined]


def test_flow_validate_data_unregistered_param_treated_as_required() -> None:
    flow = Flow(params=["nonexistent"], steps=[EvalStep(name="s1")])
    with pytest.raises(ValueError, match="Missing required param"):
        flow.validate_data({})


def test_dom_step_sanitizes_at_low_unless_told_otherwise() -> None:
    assert DomStep(name="s", action="dom", selector="#x").level is SanitizeLevel.LOW
    step = validate_step(
        {"name": "s", "action": "dom", "selector": "#x", "level": "xhigh"}
    )
    assert isinstance(step, DomStep)
    assert step.level is SanitizeLevel.XHIGH


def _read_with_extract(**kwargs: object) -> ReadStep:
    return ReadStep(
        name="s",
        action="read",
        selector="#x",
        extract={"name": {"attribute": "textContent"}},
        **kwargs,  # type: ignore[arg-type]
    )


def test_a_step_expects_nothing_until_a_minimum_is_declared() -> None:
    assert DomStep(name="s", action="dom", selector="#x").min_chars == 0
    read = ReadStep(name="s", action="read", selector="#x")
    assert (read.min_chars, read.min_rows) == (0, 0)
    assert _read_with_extract(min_rows=3).min_rows == 3


def test_min_rows_without_extract_is_rejected_when_the_flow_loads() -> None:
    """Every row of an extract-less read is empty, so no minimum could be met."""
    with pytest.raises(ValidationError, match="min_rows requires extract"):
        validate_step({"name": "s", "action": "read", "selector": "#x", "min_rows": 3})


def test_parse_takes_the_same_minimums_as_read() -> None:
    step = validate_step(
        {
            "name": "s",
            "action": "parse",
            "selector": "#x",
            "schema_path": "repo.yaml",
            "min_rows": 2,
            "min_chars": 5,
        }
    )
    assert isinstance(step, ParseStep)
    assert (step.min_rows, step.min_chars) == (2, 5)


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("td.name@href", ("td.name", "href")),
        ("", (None, "textContent")),
        ("@href", (None, "href")),
        ("td.name", ("td.name", "textContent")),
        ({"child_selector": "td.name", "attribute": "href"}, ("td.name", "href")),
    ],
)
def test_a_read_takes_the_compact_extract_form_docs_advertise(
    spec: object, expected: tuple[str | None, str]
) -> None:
    step = validate_step(
        {"name": "s", "action": "read", "selector": "tr", "extract": {"a": spec}}
    )
    assert isinstance(step, ReadStep)
    field = step.extract["a"]
    assert (field.child_selector, field.attribute) == expected


@pytest.mark.parametrize("spec", [["td.name"], 5, None])
def test_an_extract_spec_that_is_neither_string_nor_mapping_fails_validation(
    spec: object,
) -> None:
    """It used to escape as a `TypeError` traceback out of `llm-browser validate`."""
    with pytest.raises(ValidationError, match="invalid extract spec"):
        validate_step(
            {"name": "s", "action": "read", "selector": "tr", "extract": {"a": spec}}
        )


def test_type_delay_accepts_a_constant_or_a_pair() -> None:
    step = validate_step({"name": "s", "action": "type", "selector": "#x", "delay": 60})
    assert isinstance(step, TypeStep) and step.delay == 60
    step = validate_step(
        {"name": "s", "action": "type", "selector": "#x", "delay": [30, 90]}
    )
    assert isinstance(step, TypeStep)
    assert step.delay == Jitter(min_ms=30, max_ms=90)


@pytest.mark.parametrize("delay", [[90, 30], [50], [10, 20, 30], [-5, 20]])
def test_type_delay_rejects_anything_but_a_min_max_pair(delay: list[int]) -> None:
    with pytest.raises(ValidationError, match=r"\[min_ms, max_ms\]"):
        validate_step({"name": "s", "action": "type", "selector": "#x", "delay": delay})


def test_humanize_defaults_to_following_the_session() -> None:
    click = validate_step({"name": "s", "action": "click", "selector": "#x"})
    typed = validate_step({"name": "s", "action": "type", "selector": "#x"})
    assert isinstance(click, ClickStep) and isinstance(typed, TypeStep)
    assert (click.humanize, typed.humanize) == (None, None)
    forced = validate_step(
        {"name": "s", "action": "click", "selector": "#x", "humanize": True}
    )
    assert isinstance(forced, ClickStep) and forced.humanize is True
