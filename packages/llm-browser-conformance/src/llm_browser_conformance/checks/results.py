"""What ``run_flow`` hands back: the success value, the failure value, and the
two keyword arguments that change them.

The fixtures here are deliberately dull. Nothing in this module is about the
browser — every assertion is about ``FlowSuccess.outputs``, ``FlowError`` and
``RetryHint``, so a driver has almost nothing to disagree about.
"""

import base64
from collections.abc import Iterable

from llm_browser.constants import REDACTED
from llm_browser.flows import run_flow
from llm_browser.models import FlowError, FlowResult, FlowSuccess
from llm_browser.results import BytesResult, ErrorResult

from llm_browser_conformance.checks.support import error_message
from llm_browser_conformance.scenario import Context, Scenario, Section, raises

SECRET = "hunter2-swordfish"

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def run(
    ctx: Context,
    page: str,
    flow: str,
    data: dict[str, object] | None = None,
    *,
    from_step: str | None = None,
    redact: Iterable[str] = (),
) -> FlowResult:
    """``support.run``, plus the two keywords these scenarios exist to pin."""
    ctx.visit(page)
    return run_flow(
        ctx.session,
        ctx.flow(flow),
        dict(data or {}),
        from_step=from_step,
        redact=redact,
    )


def succeeded(result: FlowResult) -> FlowSuccess:
    assert isinstance(result, FlowSuccess), f"{result.step}: {result.data}"
    return result


def failed(result: FlowResult) -> FlowError:
    assert isinstance(result, FlowError), f"expected a failure, got {result.outputs}"
    return result


def outputs_hold_rows_and_dom_text_and_screenshot_bytes(ctx: Context) -> None:
    """One output per kind: rows, text, and bytes. Nothing is a path — the
    caller decides what, if anything, reaches disk."""
    success = succeeded(run(ctx, "result-rows.html", "result-outputs"))
    assert success.outputs["rows"] == [
        {"code": "A", "label": "alpha"},
        {"code": "B", "label": "beta"},
        None,
    ]
    panel = success.outputs["panel"]
    assert isinstance(panel, str), f"dom output is {type(panel).__name__}"
    assert "Panel text" in panel
    shot = success.outputs["shot"]
    assert isinstance(shot, BytesResult), f"screenshot output is {type(shot).__name__}"
    assert shot.content.startswith(PNG_MAGIC), shot.content[:16]
    assert success.step == "shot"


def a_json_dump_base64s_the_bytes_it_cannot_hold(ctx: Context) -> None:
    """``outputs`` keeps real bytes for a Python caller; a JSON consumer gets
    base64 rather than a serializer crash."""
    success = succeeded(run(ctx, "result-rows.html", "result-outputs"))
    shot = success.outputs["shot"]
    assert isinstance(shot, BytesResult), shot
    encoded = success.model_dump(mode="json")["outputs"]["shot"]["content"]
    assert base64.b64decode(encoded) == shot.content


def a_failure_keeps_the_outputs_collected_before_it(ctx: Context) -> None:
    failure = failed(run(ctx, "result-rows.html", "result-partial"))
    assert failure.outputs["rows"] == [{"code": "A"}, {"code": "B"}, None]
    assert failure.step == "boom"
    assert isinstance(failure.data, ErrorResult), failure.data
    assert error_message(failure)


def the_retry_hint_names_the_top_level_step_the_error_the_inner_one(
    ctx: Context,
) -> None:
    data: dict[str, object] = {"label": "quarterly"}
    failure = failed(run(ctx, "result-rows.html", "result-subflow", data))
    assert failure.step == "nested/boom"
    hint = failure.retry_hint
    assert hint is not None
    assert hint.flow_path == "", "only run_flow_file knows the path"
    assert hint.data == data
    assert hint.failed_step == "nested", "--from operates on top-level names"
    assert hint.error


def redact_replaces_the_secret_everywhere_it_would_have_escaped(ctx: Context) -> None:
    data: dict[str, object] = {"secret": SECRET}

    # Without `redact=` first, or every assertion below is vacuous.
    exposed = failed(run(ctx, "result-echo.html", "result-redact", data))
    assert exposed.outputs["echo"] == [{"text": SECRET}]
    assert SECRET in error_message(exposed)

    hidden = failed(
        run(ctx, "result-echo.html", "result-redact", data, redact=[SECRET])
    )
    assert hidden.outputs["echo"] == [{"text": REDACTED}]
    assert SECRET not in str(hidden.data)
    assert REDACTED in error_message(hidden)
    hint = hidden.retry_hint
    assert hint is not None
    assert hint.data == {"secret": REDACTED}
    assert SECRET not in hint.error
    assert REDACTED in hint.error


def from_step_starts_the_flow_at_a_later_step(ctx: Context) -> None:
    whole = succeeded(run(ctx, "result-rows.html", "result-from-step"))
    assert set(whole.outputs) == {"panel", "rows"}

    resumed = succeeded(
        run(ctx, "result-rows.html", "result-from-step", from_step="rows")
    )
    assert set(resumed.outputs) == {"rows"}

    unknown = raises(
        ValueError,
        lambda: run(ctx, "result-rows.html", "result-from-step", from_step="nope"),
    )
    assert "nope" in str(unknown)
    assert "panel" in str(unknown) and "rows" in str(unknown)


SCENARIOS = [
    Scenario(
        "outputs shape",
        Section.RESULTS,
        outputs_hold_rows_and_dom_text_and_screenshot_bytes,
        covers=frozenset({"api:outputs.shape"}),
    ),
    Scenario(
        "outputs json dump",
        Section.RESULTS,
        a_json_dump_base64s_the_bytes_it_cannot_hold,
        covers=frozenset({"api:outputs.json"}),
    ),
    Scenario(
        "error keeps partial outputs",
        Section.RESULTS,
        a_failure_keeps_the_outputs_collected_before_it,
        covers=frozenset({"api:error.outputs"}),
    ),
    Scenario(
        "retry hint",
        Section.RESULTS,
        the_retry_hint_names_the_top_level_step_the_error_the_inner_one,
        covers=frozenset({"api:retry_hint"}),
    ),
    Scenario(
        "redact",
        Section.RESULTS,
        redact_replaces_the_secret_everywhere_it_would_have_escaped,
        covers=frozenset({"api:redact"}),
    ),
    Scenario(
        "from_step",
        Section.RESULTS,
        from_step_starts_the_flow_at_a_later_step,
        covers=frozenset({"api:from_step"}),
    ),
]
