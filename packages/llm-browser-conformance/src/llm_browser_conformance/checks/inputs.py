"""Input conformance: the values land, and the events are trusted.

``form.html`` records ``event.isTrusted`` for the last click and the last
keydown on every element, so driver rule 2 — real input, never synthetic
events — is checked from the page's side rather than taken on faith.
"""

from llm_browser_conformance.scenario import (
    POLL_MS,
    Context,
    Scenario,
    Section,
)


def dynamic_loading_spinner_then_result(ctx: Context) -> None:
    ctx.visit("dynamic-loading.html")
    ctx.session.click("#start")
    ctx.wait_now("#loading", "detached")
    ctx.wait_now("#finish", "attached")
    assert (
        ctx.session.driver.text_content(ctx.session.find("#finish")) == "Hello World!"
    )


def dynamic_controls_remove_then_re_add(ctx: Context) -> None:
    ctx.visit("dynamic-controls.html")
    ctx.session.click("#toggle")
    ctx.wait_now("#checkbox", "detached")
    ctx.session.click("#toggle")
    ctx.wait_now("#checkbox", "attached")


def dynamic_controls_enable_makes_the_input_writable(ctx: Context) -> None:
    ctx.visit("dynamic-controls.html")
    ctx.session.click("#enable")
    ctx.wait_now("#message", "attached")
    ctx.wait_now("#input", "visible")
    ctx.session.fill("#input", "now editable")
    assert ctx.session.driver.input_value(ctx.session.find("#input")) == "now editable"


def fill_type_and_check_land_their_values(ctx: Context) -> None:
    ctx.visit("form.html")
    ctx.session.fill("#name", "Ada")
    ctx.session.type("#password", "s3cret")
    ctx.session.set_checked("#agree", True)
    assert ctx.session.driver.input_value(ctx.session.find("#name")) == "Ada"
    assert ctx.session.driver.input_value(ctx.session.find("#password")) == "s3cret"
    assert ctx.js("document.querySelector('#agree').checked") is True
    ctx.session.set_checked("#agree", False)
    assert ctx.js("document.querySelector('#agree').checked") is False


def select_option_changes_the_selects_value(ctx: Context) -> None:
    ctx.visit("form.html")
    ctx.session.select_option("#choice", "b")
    assert ctx.value("#choice") == "b"


def a_hidden_input_is_readable_without_being_visible(ctx: Context) -> None:
    ctx.visit("form.html")
    element = ctx.session.find("#secret", state="attached")
    assert ctx.session.driver.get_attribute(element, "value") == "hidden-value"


def a_click_is_a_trusted_event(ctx: Context) -> None:
    ctx.visit("form.html")
    ctx.session.click("#reveal")
    assert ctx.trusted("#reveal") == "true"


def a_key_press_is_a_trusted_event(ctx: Context) -> None:
    ctx.visit("form.html")
    ctx.session.press("#password", "Enter")
    assert ctx.trusted("#password") == "true"


def typing_fires_trusted_input_events(ctx: Context) -> None:
    """The value arrives through real input, whatever key events came with it."""
    ctx.visit("form.html")
    ctx.session.type("#name", "ab")
    assert ctx.trusted("#name", "data-trusted-input") == "true"


def typing_fires_trusted_key_events(ctx: Context) -> None:
    """Separate from the ``input`` event above because a driver can deliver a
    trusted value without ever emitting a keydown, and a page that watches
    keystrokes (masks, autocompletes, hotkeys) will not react to it."""
    ctx.visit("form.html")
    ctx.session.type("#name", "ab")
    assert ctx.trusted("#name") == "true"


def a_dispatched_click_is_reported_untrusted(ctx: Context) -> None:
    """``dispatch=True`` is rule 2's documented opt-out; the page must be able
    to tell, or the escape hatch is indistinguishable from real input."""
    ctx.visit("form.html")
    ctx.session.click("#reveal", dispatch=True)
    assert ctx.trusted("#reveal") == "false"


def a_revealed_control_becomes_fillable(ctx: Context) -> None:
    ctx.visit("form.html")
    ctx.session.click("#reveal")
    ctx.wait_now("#extra", "visible", timeout=2 * POLL_MS + 1000)
    ctx.session.fill("#extra", "second")
    assert ctx.session.driver.input_value(ctx.session.find("#extra")) == "second"


SCENARIOS = [
    Scenario(
        "dynamic loading",
        Section.INPUTS,
        dynamic_loading_spinner_then_result,
    ),
    Scenario(
        "dynamic controls toggle",
        Section.INPUTS,
        dynamic_controls_remove_then_re_add,
    ),
    Scenario(
        "dynamic controls enable",
        Section.INPUTS,
        dynamic_controls_enable_makes_the_input_writable,
    ),
    Scenario(
        "fill/type/check",
        Section.INPUTS,
        fill_type_and_check_land_their_values,
    ),
    Scenario(
        "select_option",
        Section.INPUTS,
        select_option_changes_the_selects_value,
    ),
    Scenario(
        "hidden input is readable",
        Section.INPUTS,
        a_hidden_input_is_readable_without_being_visible,
    ),
    Scenario(
        "click is trusted",
        Section.INPUTS,
        a_click_is_a_trusted_event,
    ),
    Scenario(
        "press is trusted",
        Section.INPUTS,
        a_key_press_is_a_trusted_event,
    ),
    Scenario(
        "typing fires trusted input",
        Section.INPUTS,
        typing_fires_trusted_input_events,
    ),
    Scenario(
        "typing fires trusted keydown",
        Section.INPUTS,
        typing_fires_trusted_key_events,
    ),
    Scenario(
        "dispatch is untrusted",
        Section.INPUTS,
        a_dispatched_click_is_reported_untrusted,
        known_gaps={
            "camoufox": "Gecko marks an event dispatched from Playwright's "
            "chrome-privileged agent as trusted, so dispatch=True is "
            "indistinguishable from real input on Firefox"
        },
    ),
    Scenario(
        "revealed control is fillable",
        Section.INPUTS,
        a_revealed_control_becomes_fillable,
    ),
]
