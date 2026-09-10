"""Every ``wait_for`` state against the page built for it, plus the three
things a wait must refuse to do: return early, wait out an ambiguous
selector, and poll a settle window that cannot fit its budget.
"""

from llm_browser_conformance.scenario import (
    POLL_MS,
    SETTLE_MS,
    Context,
    Scenario,
    Section,
    raises,
)

IMMEDIATE_S = POLL_MS / 1000


def attached_waits_for_a_late_insert(ctx: Context) -> None:
    timing = ctx.timed(
        lambda: ctx.visit("attached.html"), ctx.wait("#late", "attached")
    )
    timing.assert_within(ctx.delay_ms)


def detached_waits_for_a_removal(ctx: Context) -> None:
    ctx.visit("detached.html")
    timing = ctx.timed(
        lambda: ctx.session.click("#close"), ctx.wait(".modal", "detached")
    )
    timing.assert_within(ctx.delay_ms)


def visible_waits_for_display_to_flip(ctx: Context) -> None:
    timing = ctx.timed(lambda: ctx.visit("visible.html"), ctx.wait("#btn", "visible"))
    timing.assert_within(ctx.delay_ms)


def hidden_waits_for_the_element_to_stop_rendering(ctx: Context) -> None:
    timing = ctx.timed(lambda: ctx.visit("hidden.html"), ctx.wait("#banner", "hidden"))
    timing.assert_within(ctx.delay_ms)


def stable_waits_for_the_text_to_stop_moving(ctx: Context) -> None:
    """``#total`` ticks for the whole delay, so the settle window can only
    close once the ticking has stopped."""
    timing = ctx.timed(
        lambda: ctx.visit("stable.html"),
        ctx.wait("#total", "stable", settle=SETTLE_MS),
    )
    timing.assert_within(ctx.delay_ms, extra_ms=SETTLE_MS)


def attached_returns_at_once_for_an_element_already_there(ctx: Context) -> None:
    ctx.visit("visible.html")
    assert ctx.elapsed(ctx.wait("#btn", "attached")) < IMMEDIATE_S


def visibility_hidden_counts_as_hidden(ctx: Context) -> None:
    ctx.visit("visible.html")
    assert ctx.elapsed(ctx.wait("#invisible", "hidden")) < IMMEDIATE_S


def opacity_zero_counts_as_visible(ctx: Context) -> None:
    """Pinned because it is agreement, not an obvious answer: Playwright's
    check (non-empty box, ``visibility != hidden``) and nodriver's
    ``offsetParent`` check both call a fully transparent element visible."""
    ctx.visit("visible.html")
    assert ctx.elapsed(ctx.wait("#transparent", "visible")) < IMMEDIATE_S


def a_short_timeout_names_selector_and_state(ctx: Context) -> None:
    ctx.visit("attached.html")
    error = raises(
        TimeoutError,
        lambda: ctx.wait_now("#late", "attached", timeout=400),
    )
    assert str(error) == "#late did not become attached within 400ms"


def detached_times_out_on_an_element_that_only_hides(ctx: Context) -> None:
    ctx.visit("hidden.html")
    raises(
        TimeoutError,
        lambda: ctx.wait_now("#banner", "detached", timeout=ctx.delay_ms + 1000),
    )


def a_settle_that_does_not_fit_the_budget_is_rejected_before_polling(
    ctx: Context,
) -> None:
    ctx.visit("stable.html")
    took = ctx.elapsed(
        lambda: raises(
            ValueError,
            lambda: ctx.wait_now("#total", "stable", settle=1000, timeout=1000),
        )
    )
    assert took < IMMEDIATE_S


def find_rejects_an_ambiguous_selector_at_once(ctx: Context) -> None:
    ctx.visit("ambiguous.html")
    took = ctx.elapsed(lambda: raises(ValueError, lambda: ctx.session.find(".item")))
    assert took < IMMEDIATE_S


SCENARIOS = [
    Scenario(
        "wait attached",
        Section.WAITS,
        attached_waits_for_a_late_insert,
    ),
    Scenario("wait detached", Section.WAITS, detached_waits_for_a_removal),
    Scenario("wait visible", Section.WAITS, visible_waits_for_display_to_flip),
    Scenario(
        "wait hidden",
        Section.WAITS,
        hidden_waits_for_the_element_to_stop_rendering,
    ),
    Scenario(
        "wait stable",
        Section.WAITS,
        stable_waits_for_the_text_to_stop_moving,
    ),
    Scenario(
        "attached is immediate",
        Section.WAITS,
        attached_returns_at_once_for_an_element_already_there,
    ),
    Scenario(
        "visibility:hidden is hidden",
        Section.WAITS,
        visibility_hidden_counts_as_hidden,
        known_gaps={
            "nodriver": "is_visible tests offsetParent/getClientRects, neither "
            "of which notices visibility:hidden"
        },
    ),
    Scenario(
        "opacity:0 is visible",
        Section.WAITS,
        opacity_zero_counts_as_visible,
    ),
    Scenario(
        "timeout message",
        Section.WAITS,
        a_short_timeout_names_selector_and_state,
    ),
    Scenario(
        "detached times out on hidden",
        Section.WAITS,
        detached_times_out_on_an_element_that_only_hides,
    ),
    Scenario(
        "settle must fit timeout",
        Section.WAITS,
        a_settle_that_does_not_fit_the_budget_is_rejected_before_polling,
    ),
    Scenario(
        "find rejects ambiguity",
        Section.WAITS,
        find_rejects_an_ambiguous_selector_at_once,
    ),
]
