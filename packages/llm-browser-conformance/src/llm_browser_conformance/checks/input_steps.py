"""Input steps must leave the field holding what the flow asked for, or fail.

Each case runs under the default profile and under ``Behavior.human()``, the
one a hosted server runs with: a humanized ``fill`` types its value, so a
step that works plain can still append to a prefilled field.
"""

from llm_browser.behavior import Behavior
from llm_browser.flows import run_flow
from llm_browser.models import FlowError, FlowSuccess

from llm_browser_conformance.checks.support import error_message, one_text
from llm_browser_conformance.scenario import Context, Scenario, Section

PROFILES = {"off": Behavior.off(), "human": Behavior.human()}

PREFILLED = "prefilled-autocomplete.html"
STUBBORN = "fill-does-not-stick.html"
HIDDEN = "hidden-checkbox.html"

HUMANIZED_FILL_APPENDS = (
    "a humanized fill types without clearing, so it appends to a prefilled field"
)
FILL_NOT_VERIFIED = "fill reports ok without reading the field back"
NO_CLEAN_STEP = "there is no clean step"
NO_VALUE_WAIT = "wait_for has no value: key, so it ignores the value asked for"
NO_CHECK_DISPATCH = "check has no dispatch: key, so a hidden box is never reached"
ALL_DRIVERS = ("patchright", "camoufox", "nodriver")


def on_every_driver(gap: str) -> dict[str, str]:
    return dict.fromkeys(ALL_DRIVERS, gap)


def run(
    ctx: Context, page: str, flow: str, behavior: Behavior
) -> FlowSuccess | FlowError:
    ctx.visit(page)
    result = run_flow(ctx.session, ctx.flow(flow), {}, behavior=behavior)
    assert isinstance(result, FlowSuccess | FlowError), result
    return result


def expect_success(
    ctx: Context, page: str, flow: str, *, behavior: Behavior
) -> dict[str, object]:
    result = run(ctx, page, flow, behavior)
    assert isinstance(result, FlowSuccess), f"{result.step}: {result.data}"
    return result.outputs


def expect_failure(
    ctx: Context, page: str, flow: str, *, behavior: Behavior
) -> FlowError:
    result = run(ctx, page, flow, behavior)
    assert isinstance(result, FlowError), f"expected a failure, got {result.outputs}"
    return result


def a_prefilled_autocomplete_is_cleared_before_typing(ctx: Context) -> None:
    for profile, behavior in PROFILES.items():
        outputs = expect_success(
            ctx, PREFILLED, "prefilled-autocomplete-clear", behavior=behavior
        )
        assert one_text(outputs, "cleared") == "", profile
        assert one_text(outputs, "typed") == "Peso", profile
        assert one_text(outputs, "result") == "Peso Mexicano", profile


def a_fill_replaces_a_prefilled_value(ctx: Context) -> None:
    for profile, behavior in PROFILES.items():
        outputs = expect_success(
            ctx, PREFILLED, "prefilled-autocomplete-fill", behavior=behavior
        )
        assert one_text(outputs, "filled") == "Peso", profile


def clean_empties_a_prefilled_field(ctx: Context) -> None:
    for profile, behavior in PROFILES.items():
        outputs = expect_success(
            ctx, PREFILLED, "prefilled-autocomplete-clean", behavior=behavior
        )
        assert one_text(outputs, "cleaned") == "", profile


def a_fill_that_does_not_stick_fails_clearly(ctx: Context) -> None:
    for profile, behavior in PROFILES.items():
        failure = expect_failure(
            ctx, STUBBORN, "fill-does-not-stick", behavior=behavior
        )
        assert failure.step == "fill", profile
        message = error_message(failure)
        assert "beta" in message and "alpha" in message, f"{profile}: {message}"


def verify_exact_fails_where_the_default_passes(ctx: Context) -> None:
    """``maxlength`` keeps a prefix: the field changed, so only ``exact`` objects."""
    for profile, behavior in PROFILES.items():
        outputs = expect_success(ctx, STUBBORN, "fill-maxlength", behavior=behavior)
        assert one_text(outputs, "filled") == "abc", profile
        failure = expect_failure(
            ctx, STUBBORN, "fill-maxlength-exact", behavior=behavior
        )
        message = error_message(failure)
        assert "abcdef" in message and "'abc'" in message, f"{profile}: {message}"


def wait_for_value_reads_the_field(ctx: Context) -> None:
    for profile, behavior in PROFILES.items():
        expect_success(
            ctx, PREFILLED, "prefilled-autocomplete-wait-value", behavior=behavior
        )
        failure = expect_failure(
            ctx, PREFILLED, "prefilled-autocomplete-wait-value-wrong", behavior=behavior
        )
        assert failure.step == "picked", profile
        message = error_message(failure)
        assert "Peso Mexicano" in message, f"{profile}: {message}"


def a_hidden_checkbox_can_be_checked_when_dispatched(ctx: Context) -> None:
    for profile, behavior in PROFILES.items():
        expect_success(ctx, HIDDEN, "hidden-checkbox-dispatch", behavior=behavior)
        assert ctx.js("document.querySelector('#exento').checked") is True, profile


def a_hidden_checkbox_without_dispatch_fails_clearly(ctx: Context) -> None:
    for profile, behavior in PROFILES.items():
        failure = expect_failure(
            ctx, HIDDEN, "hidden-checkbox-plain", behavior=behavior
        )
        message = error_message(failure)
        assert "visible" in message.lower(), f"{profile}: {message}"


def a_disabled_hidden_checkbox_fails_when_dispatched(ctx: Context) -> None:
    for profile, behavior in PROFILES.items():
        failure = expect_failure(
            ctx, HIDDEN, "hidden-checkbox-disabled", behavior=behavior
        )
        message = error_message(failure)
        assert "checked" in message, f"{profile}: {message}"


SCENARIOS = [
    Scenario(
        "prefilled autocomplete clear",
        Section.STEPS,
        a_prefilled_autocomplete_is_cleared_before_typing,
        known_gaps=on_every_driver(HUMANIZED_FILL_APPENDS),
        covers=frozenset({"step:fill", "field:fill.value"}),
    ),
    Scenario(
        "prefilled autocomplete fill",
        Section.STEPS,
        a_fill_replaces_a_prefilled_value,
        known_gaps=on_every_driver(HUMANIZED_FILL_APPENDS),
        covers=frozenset({"step:fill", "field:fill.value"}),
    ),
    Scenario(
        "clean step",
        Section.STEPS,
        clean_empties_a_prefilled_field,
        known_gaps=on_every_driver(NO_CLEAN_STEP),
    ),
    Scenario(
        "fill does not stick",
        Section.STEPS,
        a_fill_that_does_not_stick_fails_clearly,
        known_gaps=on_every_driver(FILL_NOT_VERIFIED),
        covers=frozenset({"step:fill"}),
    ),
    Scenario(
        "fill verify exact",
        Section.STEPS,
        verify_exact_fails_where_the_default_passes,
        known_gaps=on_every_driver(FILL_NOT_VERIFIED),
        covers=frozenset({"step:fill"}),
    ),
    Scenario(
        "wait_for value",
        Section.STEPS,
        wait_for_value_reads_the_field,
        known_gaps=on_every_driver(NO_VALUE_WAIT),
        covers=frozenset({"step:wait_for", "step:pick"}),
    ),
    Scenario(
        "hidden checkbox dispatch",
        Section.STEPS,
        a_hidden_checkbox_can_be_checked_when_dispatched,
        known_gaps=on_every_driver(NO_CHECK_DISPATCH),
        covers=frozenset({"step:check"}),
    ),
    Scenario(
        "hidden checkbox plain",
        Section.STEPS,
        a_hidden_checkbox_without_dispatch_fails_clearly,
        covers=frozenset({"step:check"}),
    ),
    Scenario(
        "hidden checkbox disabled",
        Section.STEPS,
        a_disabled_hidden_checkbox_fails_when_dispatched,
        known_gaps=on_every_driver(NO_CHECK_DISPATCH),
        covers=frozenset({"step:check"}),
    ),
]
