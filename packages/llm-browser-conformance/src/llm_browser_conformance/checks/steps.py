"""Whole-page hazards: overlays, sticky headers, shadow roots, frames,
redirects, downloads, keyboard-only flows, new tabs and trickling XHR.

Each one is a shape that has broken a real automation run, reduced to a
self-contained page and the flow that has to survive it.
"""

import tempfile
from pathlib import Path

from llm_browser.models import FlowSuccess

from llm_browser_conformance.checks.frames import enter_frame_or_skip
from llm_browser_conformance.checks.support import (
    error_message,
    expect_success,
    one_text,
    run,
    texts,
)
from llm_browser_conformance.scenario import Context, Scenario, Section

DOWNLOAD_PAYLOAD = "conformance-payload"


def an_overlay_is_waited_out_before_the_click(ctx: Context) -> None:
    outputs = expect_success(ctx, "overlay.html", "overlay")
    assert one_text(outputs, "result") == "clicked"
    assert ctx.trusted("#btn") == "true"


def a_click_lands_under_a_sticky_header(ctx: Context) -> None:
    """The button is 3000px down; a driver that scrolls it to the very top of
    the viewport hands the click to the fixed header instead."""
    outputs = expect_success(ctx, "sticky-header.html", "sticky-header")
    landed = one_text(outputs, "result")
    assert landed == "clicked", f"the click reached {landed!r}"


def a_click_on_a_still_disabled_button(ctx: Context) -> str:
    """Recorded, not forced: Playwright's click waits for the button to become
    enabled, while a driver that dispatches straight away clicks the floor.
    Both are defensible; the table says which one you have."""
    result = run(ctx, "disabled-button.html", "disabled-button")
    if not isinstance(result, FlowSuccess):
        return f"click failed while disabled: {error_message(result)}"
    clicked = one_text(result.outputs, "result")
    if clicked == "clicked":
        return "click waited for the button to become enabled"
    return "click landed on the disabled button and did nothing"


def an_open_shadow_root_is_reachable(ctx: Context) -> None:
    """A driver whose selectors do not pierce is a known gap, not a skip: any
    other failure here — the fill regressing, the click missing, the result
    coming back empty — has to be able to turn this row red."""
    outputs = expect_success(ctx, "shadow-dom.html", "shadow-dom")
    assert one_text(outputs, "result") == "shadow value"


def dom_returns_the_elements_own_markup(ctx: Context) -> None:
    """``session.dom`` reads ``el => el.outerHTML``: a driver that runs that
    string as anything but a function gets ``None`` and says nothing."""
    ctx.visit("form.html")
    markup = ctx.session.dom("#choice")
    assert 'id="choice"' in markup, markup
    assert 'value="b"' in markup, markup


def a_form_inside_an_iframe_is_filled_and_submitted(ctx: Context) -> None:
    ctx.visit("iframe-form.html")
    frame = enter_frame_or_skip(ctx)
    driver = ctx.session.driver
    driver.fill(driver.first(driver.resolve(frame, "#child-name")), "Ada")
    driver.click(driver.first(driver.resolve(frame, "#child-submit")))
    assert ctx.text("#result") == "Ada"


def a_redirect_is_followed_to_late_content(ctx: Context) -> None:
    # never.html is only a neutral starting page; the flow's goto is the test.
    outputs = expect_success(ctx, "never.html", "redirect", url=ctx.url("redirect"))
    assert one_text(outputs, "result") == "arrived"


def a_download_lands_on_disk(ctx: Context) -> None:
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "payload.txt"
        try:
            expect_success(ctx, "download.html", "download", path=str(target))
        except NotImplementedError as exc:
            raise ctx.skip(str(exc)) from exc
        assert target.read_text().strip() == DOWNLOAD_PAYLOAD


def tab_moves_focus_to_the_next_field(ctx: Context) -> None:
    ctx.visit("keyboard.html")
    ctx.session.click("#first")
    ctx.session.press("#first", "Tab")
    assert ctx.js("document.activeElement.id") == "second"


def enter_submits_and_escape_closes(ctx: Context) -> None:
    outputs = expect_success(ctx, "keyboard.html", "keyboard")
    assert one_text(outputs, "result") == "submitted"


def a_target_blank_link_leaves_the_session_where_it_was(ctx: Context) -> str:
    """Recorded, not forced: the contract is only that the session keeps
    driving the page it was on. Whether a second tab exists is the driver's
    business, and ``latest_tab`` is how a caller would go and find it."""
    expect_success(ctx, "new-tab.html", "new-tab")
    current = ctx.session.driver.page_url(ctx.session.get_page())
    assert "new-tab.html" in current, current
    return "session stayed on the opener"


def rows_that_trickle_in_are_all_read_once_stable(ctx: Context) -> None:
    outputs = expect_success(ctx, "slow-xhr.html", "slow-xhr")
    rows = texts(outputs, "rows")
    assert rows == [f"row-{n}" for n in range(1, 6)], rows


SCENARIOS = [
    Scenario(
        "overlay intercepts click",
        Section.STEPS,
        an_overlay_is_waited_out_before_the_click,
    ),
    Scenario(
        "sticky header",
        Section.STEPS,
        a_click_lands_under_a_sticky_header,
        known_gaps={
            "nodriver": "click does not scroll the target into view, so the "
            "CDP mouse event is dispatched at viewport coordinates the button "
            "is not at and nothing is clicked"
        },
    ),
    Scenario(
        "disabled button",
        Section.STEPS,
        a_click_on_a_still_disabled_button,
    ),
    Scenario(
        "shadow dom",
        Section.STEPS,
        an_open_shadow_root_is_reachable,
        known_gaps={
            "nodriver": "selectors do not pierce an open shadow root, so the "
            "input inside it is never found"
        },
    ),
    Scenario(
        "dom snippet",
        Section.STEPS,
        dom_returns_the_elements_own_markup,
    ),
    Scenario(
        "iframe form",
        Section.STEPS,
        a_form_inside_an_iframe_is_filled_and_submitted,
    ),
    Scenario(
        "redirect",
        Section.STEPS,
        a_redirect_is_followed_to_late_content,
    ),
    Scenario("download", Section.STEPS, a_download_lands_on_disk),
    Scenario("tab order", Section.STEPS, tab_moves_focus_to_the_next_field),
    Scenario(
        "enter and escape",
        Section.STEPS,
        enter_submits_and_escape_closes,
    ),
    Scenario(
        "new tab",
        Section.STEPS,
        a_target_blank_link_leaves_the_session_where_it_was,
    ),
    Scenario(
        "slow xhr rows",
        Section.STEPS,
        rows_that_trickle_in_are_all_read_once_stable,
    ),
]
