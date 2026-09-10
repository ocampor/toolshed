"""Form controls that fight back: controlled inputs, masks, debounced
autocompletes, fake dropdowns and real ones.

These are the shapes that break naive automation — a value written in one
shot, a click that never reaches the option, a list that is not there yet —
so they are where drivers actually differ.
"""

from llm_browser_conformance.checks.support import (
    error_message,
    expect_failure,
    expect_success,
    one_text,
)
from llm_browser_conformance.scenario import Context, Scenario, Section


def a_controlled_input_keeps_what_fill_and_type_write(ctx: Context) -> None:
    """The page reverts any value that arrived without an ``input`` event, so
    a driver that writes ``.value`` directly loses it half a tick later."""
    outputs = expect_success(ctx, "react-input.html", "react-input")
    assert one_text(outputs, "filled") == "alpha"
    assert one_text(outputs, "typed") == "beta"
    events = one_text(outputs, "events")
    assert events is not None and int(events) > 0, events


def a_mask_reformats_every_keystroke(ctx: Context) -> None:
    outputs = expect_success(ctx, "masked-input.html", "masked-input")
    assert one_text(outputs, "value") == "(555) 123-4567"


def a_debounced_autocomplete_can_be_clicked(ctx: Context) -> None:
    outputs = expect_success(ctx, "autocomplete.html", "autocomplete-click")
    assert one_text(outputs, "result") == "al-one"


def a_debounced_autocomplete_can_be_chosen_with_enter(ctx: Context) -> None:
    outputs = expect_success(ctx, "autocomplete.html", "autocomplete-enter")
    assert one_text(outputs, "result") == "al-one"


def a_div_dropdown_is_driven_by_clicking(ctx: Context) -> None:
    outputs = expect_success(ctx, "custom-select.html", "custom-select-click")
    assert one_text(outputs, "result") == "b"
    assert ctx.trusted("#dropdown-toggle") == "true"


def select_on_a_div_dropdown_fails_clearly(ctx: Context) -> str:
    """The value of a wrong-element error is that it says so. Drivers word it
    differently — Playwright names the ``<select>``, nodriver the missing
    ``<option>`` — so the assertion is that one of those words is in there."""
    failure = expect_failure(ctx, "custom-select.html", "custom-select-select")
    assert failure.step == "select"
    message = error_message(failure)
    assert "select" in message.lower() or "option" in message.lower(), message
    return message[:80]


def a_native_select_picks_an_option_behind_an_optgroup(ctx: Context) -> None:
    outputs = expect_success(ctx, "native-select.html", "native-select")
    assert one_text(outputs, "result") == "c"


def a_disabled_option_cannot_be_selected(ctx: Context) -> None:
    failure = expect_failure(ctx, "native-select.html", "native-select-disabled")
    assert failure.step == "select"


def an_invisible_checkbox_and_a_radio_group_toggle(ctx: Context) -> None:
    outputs = expect_success(ctx, "checkbox-radio.html", "checkbox-radio")
    assert one_text(outputs, "result") == "green"
    assert ctx.js("document.querySelector('#agree').checked") is False
    assert ctx.js("document.querySelector('#red').checked") is False


SCENARIOS = [
    Scenario(
        "controlled input",
        Section.STEPS,
        a_controlled_input_keeps_what_fill_and_type_write,
        "react-input.html",
    ),
    Scenario(
        "masked input",
        Section.STEPS,
        a_mask_reformats_every_keystroke,
        "masked-input.html",
    ),
    Scenario(
        "autocomplete click",
        Section.STEPS,
        a_debounced_autocomplete_can_be_clicked,
        "autocomplete.html",
    ),
    Scenario(
        "autocomplete enter",
        Section.STEPS,
        a_debounced_autocomplete_can_be_chosen_with_enter,
        "autocomplete.html",
    ),
    Scenario(
        "custom select click",
        Section.STEPS,
        a_div_dropdown_is_driven_by_clicking,
        "custom-select.html",
    ),
    Scenario(
        "custom select rejects select",
        Section.STEPS,
        select_on_a_div_dropdown_fails_clearly,
        "custom-select.html",
        # Not a driver difference: execute_action only converts TimeoutError
        # and ValueError into an ErrorResult, so a wrong-element select
        # escapes run_flow as a raw driver exception on every backend --
        # `optional:` cannot swallow it and the CLI cannot report it.
        known_gaps=dict.fromkeys(
            ("patchright", "camoufox", "nodriver"),
            "select on a non-<select> raises out of run_flow instead of "
            "returning a FlowError",
        ),
    ),
    Scenario(
        "native select optgroup",
        Section.STEPS,
        a_native_select_picks_an_option_behind_an_optgroup,
        "native-select.html",
        known_gaps={
            "nodriver": "select_option native-clicks the <option>; a closed "
            "native select ignores it and the value never changes"
        },
    ),
    Scenario(
        "native select disabled option",
        Section.STEPS,
        a_disabled_option_cannot_be_selected,
        "native-select.html",
        known_gaps={
            "nodriver": "clicking a disabled <option> is a no-op, so the step "
            "reports success instead of failing"
        },
    ),
    Scenario(
        "checkbox and radio",
        Section.STEPS,
        an_invisible_checkbox_and_a_radio_group_toggle,
        "checkbox-radio.html",
    ),
]
