"""The options every step carries, the ``when:`` gate, templating and params.

These are the parts of a flow that are not an action: the fields on
``BaseStep`` that every step type inherits, the conditions that decide whether
a step runs at all, the ``{{ }}`` substitution that happens just before it
does, and the params that feed it. A gated ``read`` is the instrument
throughout — a step that was skipped leaves its name out of
``FlowSuccess.outputs``, so "did it run" is one key lookup rather than a guess
about the page.
"""

import time

from llm_browser.constants import DEFAULT_POLL_INTERVAL_MS
from llm_browser.flows import run_flow
from llm_browser.models import FlowError, FlowSuccess

from llm_browser_conformance.checks.support import (
    expect_failure,
    expect_success,
    one_text,
)
from llm_browser_conformance.scenario import (
    SLACK_MS,
    Context,
    Scenario,
    Section,
    raises,
)

PAGE = "option-steps.html"
GATED = "gated"

WAIT_AFTER_MS = 1_500
STEP_TIMEOUT_MS = 1_000

# ``find`` polls on the library's own cadence, so a budget is spent plus at
# most one more check; the rest is the machine.
BUDGET_MS = STEP_TIMEOUT_MS + 2 * DEFAULT_POLL_INTERVAL_MS + SLACK_MS


def ran(ctx: Context, flow: str, **data: object) -> bool:
    """Whether the flow's one gated ``read`` ran, by whether it left a key."""
    outputs = expect_success(ctx, PAGE, flow, **data)
    if GATED not in outputs:
        return False
    assert one_text(outputs, GATED) == "present"
    return True


def timed_run(ctx: Context, flow: str) -> float:
    """Seconds one flow costs on the page that is already loaded."""

    def go() -> None:
        result = run_flow(ctx.session, ctx.flow(flow), {})
        assert isinstance(result, FlowSuccess), result

    return ctx.elapsed(go)


# --- when: ---


def is_truthy_reads_the_flow_data(ctx: Context) -> None:
    assert ran(ctx, "when-is-truthy", flag="yes")
    assert not ran(ctx, "when-is-truthy", flag="")


def eq_ignores_case_on_both_sides(ctx: Context) -> None:
    """``compile_condition`` lowercases the declared value and ``eq``
    lowercases the data's — so ``value: Live`` matches ``"LIVE"``."""
    assert ran(ctx, "when-eq", mode="LIVE")
    assert not ran(ctx, "when-eq", mode="staging")


def not_null_cannot_tell_absent_from_null(ctx: Context) -> str:
    """``to_template_dict`` drops ``None``, so the condition never sees one:
    an explicit ``None`` and a param left out are the same missing key, and
    ``not_null`` gets ``None`` from ``.get`` either way."""
    assert ran(ctx, "when-not-null", token="abc")
    assert not ran(ctx, "when-not-null")
    assert not ran(ctx, "when-not-null", token=None)
    return "an explicit None gates the same as an omitted param"


def element_exists_asks_the_page(ctx: Context) -> None:
    assert ran(ctx, "when-element-exists", target="#present")
    assert not ran(ctx, "when-element-exists", target="#absent")


def element_missing_is_the_inverse(ctx: Context) -> None:
    assert ran(ctx, "when-element-missing", target="#absent")
    assert not ran(ctx, "when-element-missing", target="#present")


# --- The rest of BaseStep ---


def wait_after_costs_the_flow_its_milliseconds(ctx: Context) -> None:
    ctx.visit(PAGE)
    plain = timed_run(ctx, "option-plain")
    waited = timed_run(ctx, "option-wait-after")
    floor = WAIT_AFTER_MS / 1000
    assert waited >= floor, f"waited {waited:.3f}s, expected at least {floor}s"
    assert plain < floor, f"the control alone took {plain:.3f}s"
    ceiling = plain + (WAIT_AFTER_MS + SLACK_MS) / 1000
    assert waited <= ceiling, f"waited {waited:.3f}s, budget {ceiling:.3f}s"


def a_fields_block_changes_nothing(ctx: Context) -> None:
    """``fields:`` is accepted and ignored, so the block in the flow names a
    selector and an attribute that would be wrong if anything read them."""
    plain = expect_success(ctx, PAGE, "option-plain")
    declared = expect_success(ctx, PAGE, "option-fields")
    assert declared == plain, f"{declared} != {plain}"


def the_step_name_is_the_outputs_key(ctx: Context) -> None:
    assert list(expect_success(ctx, PAGE, "option-plain")) == ["gated"]
    assert list(expect_success(ctx, PAGE, "option-renamed")) == ["readout"]
    error = raises(ValueError, lambda: ctx.flow("option-duplicate-names"))
    assert "duplicate step names" in str(error), error


def a_step_timeout_bounds_the_search(ctx: Context) -> None:
    ctx.visit(PAGE)
    flow = ctx.flow("option-timeout")
    start = time.monotonic()
    failure = run_flow(ctx.session, flow, {})
    took = time.monotonic() - start
    assert isinstance(failure, FlowError), failure
    assert failure.step == "click-missing", failure.step
    assert took <= BUDGET_MS / 1000, f"failed after {took:.3f}s, budget {BUDGET_MS}ms"


def repeat_runs_one_step_once_per_item(ctx: Context) -> None:
    outputs = expect_success(
        ctx, "repeat-list.html", "repeat-read", ids=["alpha", "beta", "gamma"]
    )
    assert [one_text(outputs, f"row[{n}]") for n in range(3)] == [
        "first",
        "second",
        "third",
    ]


def repeat_indexes_a_sub_flows_outputs_too(ctx: Context) -> None:
    """The child keys stay qualified *and* indexed, so two passes of the same
    sub-flow cannot overwrite each other."""
    outputs = expect_success(
        ctx, "repeat-list.html", "repeat-subflow", ids=["alpha", "gamma"]
    )
    assert [one_text(outputs, f"each/row[{n}]") for n in range(2)] == [
        "first",
        "third",
    ]


# --- Templating and params ---


def a_selector_and_a_value_are_both_templated(ctx: Context) -> None:
    expect_success(ctx, PAGE, "option-template", target="#field", text="typed")
    assert ctx.value("#field") == "typed"


def an_unresolved_name_stays_a_literal_placeholder(ctx: Context) -> None:
    """``resolve_template`` leaves a name it cannot find alone, so the step is
    handed the placeholder itself: harmless in a value, fatal in a selector."""
    failure = expect_failure(ctx, PAGE, "option-template-miss")
    assert ctx.value("#field") == "{{ nowhere }}"
    assert failure.step == "click-missing", failure.step


def a_missing_required_param_raises(ctx: Context) -> None:
    """``validate_data`` runs before the first step, outside the per-step
    error handling — so this is an exception out of ``run_flow``, not a
    ``FlowError`` the caller can inspect."""
    ctx.visit(PAGE)
    flow = ctx.flow("option-params-required")
    error = raises(ValueError, lambda: run_flow(ctx.session, flow, {}))
    assert "Missing required param: needed" in str(error), error
    expect_success(ctx, PAGE, "option-params-required", needed="supplied")
    assert ctx.value("#field") == "supplied"


def a_default_fills_in_until_the_caller_does(ctx: Context) -> None:
    expect_success(ctx, PAGE, "option-params-default")
    assert ctx.value("#field") == "from-the-default"
    expect_success(ctx, PAGE, "option-params-default", greeting="from-the-caller")
    assert ctx.value("#field") == "from-the-caller"


SCENARIOS = [
    Scenario(
        "when is_truthy",
        Section.OPTIONS,
        is_truthy_reads_the_flow_data,
        covers=frozenset({"option:when", "when:is_truthy"}),
    ),
    Scenario(
        "when eq",
        Section.OPTIONS,
        eq_ignores_case_on_both_sides,
        covers=frozenset({"when:eq"}),
    ),
    Scenario(
        "when not_null",
        Section.OPTIONS,
        not_null_cannot_tell_absent_from_null,
        covers=frozenset({"when:not_null"}),
    ),
    Scenario(
        "when element_exists",
        Section.OPTIONS,
        element_exists_asks_the_page,
        covers=frozenset({"when:element_exists", "session:element_exists"}),
    ),
    Scenario(
        "when element_missing",
        Section.OPTIONS,
        element_missing_is_the_inverse,
        covers=frozenset({"when:element_missing"}),
    ),
    Scenario(
        "wait_after",
        Section.OPTIONS,
        wait_after_costs_the_flow_its_milliseconds,
        covers=frozenset({"option:wait_after"}),
    ),
    Scenario(
        "fields are ignored",
        Section.OPTIONS,
        a_fields_block_changes_nothing,
        covers=frozenset({"option:fields"}),
    ),
    Scenario(
        "step name keys the output",
        Section.OPTIONS,
        the_step_name_is_the_outputs_key,
        covers=frozenset({"option:name"}),
    ),
    Scenario(
        "step timeout",
        Section.OPTIONS,
        a_step_timeout_bounds_the_search,
        covers=frozenset({"option:timeout"}),
    ),
    Scenario(
        "repeat a step",
        Section.OPTIONS,
        repeat_runs_one_step_once_per_item,
        covers=frozenset({"option:repeat"}),
    ),
    Scenario(
        "repeat a sub-flow",
        Section.OPTIONS,
        repeat_indexes_a_sub_flows_outputs_too,
        covers=frozenset({"field:run-flow.data", "field:run-flow.flow"}),
    ),
    Scenario(
        "templating",
        Section.OPTIONS,
        a_selector_and_a_value_are_both_templated,
        covers=frozenset({"api:templating.selector", "api:templating.value"}),
    ),
    Scenario(
        "unresolved placeholder",
        Section.OPTIONS,
        an_unresolved_name_stays_a_literal_placeholder,
    ),
    Scenario(
        "params required",
        Section.OPTIONS,
        a_missing_required_param_raises,
        covers=frozenset({"api:params.required"}),
    ),
    Scenario(
        "params default",
        Section.OPTIONS,
        a_default_fills_in_until_the_caller_does,
        covers=frozenset({"api:params.default"}),
    ),
]
