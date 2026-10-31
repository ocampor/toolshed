"""Only a popup that renders before fetching escapes ``download_bytes``, which listens on the opener alone."""

import time
from typing import NamedTuple

from llm_browser.flows import run_flow
from llm_browser.models import FlowError, FlowSuccess
from llm_browser.results import BytesResult

from llm_browser_conformance.checks.session_api import (
    NEW_TAB_TARGET,
    tabs_closed_after,
)
from llm_browser_conformance.checks.support import error_message
from llm_browser_conformance.scenario import (
    SLACK_MS,
    Context,
    Scenario,
    Section,
)
from llm_browser_conformance.server import (
    ATTACHMENT_PDF_FILENAME,
    INLINE_PDF_FILENAME,
    PDF_MAGIC,
)

PAGE = "popup-download.html"
FLOW = "popup-download"

DEFERRED_POPUP = "popup-then-download.html"

# One reason for every row that fails for it; the issue number lands here.
POPUP_DOWNLOAD_GAP = (
    "download_bytes listens on the page the trigger was clicked on, so a file "
    "the browser delivers to another tab is never seen: see #40"
)


class Attempt(NamedTuple):
    result: FlowSuccess | FlowError
    took: float


def declared_timeout_ms(ctx: Context) -> int:
    """Read off the flow, so lowering it there cannot leave an old ceiling asserted here."""
    step = ctx.flow(FLOW).steps[0]
    return step.timeout


def download(ctx: Context, selector: str, opened: str | None = None) -> Attempt:
    """The opener is read before the click: afterwards the newest tab may be the popup."""
    ctx.visit(PAGE)
    opener = ctx.session.get_page()
    with tabs_closed_after(ctx, opener, opened):
        try:
            started = time.monotonic()
            result = run_flow(ctx.session, ctx.flow(FLOW), {"selector": selector})
            took = time.monotonic() - started
        except NotImplementedError as exc:
            raise ctx.skip(str(exc)) from exc
    assert isinstance(result, FlowSuccess | FlowError), result
    return Attempt(result, took)


def expect_pdf(
    ctx: Context, selector: str, filename: str, opened: str | None = None
) -> None:
    result = download(ctx, selector, opened).result
    assert isinstance(result, FlowSuccess), f"{result.step}: {result.data}"
    payload = result.outputs["download"]
    assert isinstance(payload, BytesResult), payload
    assert payload.content.startswith(PDF_MAGIC), payload.content[:16]
    assert payload.name == filename, payload.name


def a_same_tab_attachment_comes_back_as_bytes(ctx: Context) -> None:
    expect_pdf(ctx, "#attach", ATTACHMENT_PDF_FILENAME)


def a_popup_that_redirects_to_an_inline_pdf_is_captured(ctx: Context) -> None:
    """A headless browser has no PDF viewer, so an inline PDF downloads anyway."""
    expect_pdf(ctx, "#popup_inline", INLINE_PDF_FILENAME)


def a_popup_that_redirects_to_an_attachment_is_captured(ctx: Context) -> None:
    expect_pdf(ctx, "#popup_attach", ATTACHMENT_PDF_FILENAME)


def a_target_blank_link_to_a_file_is_captured(ctx: Context) -> None:
    expect_pdf(ctx, "#blank_link", ATTACHMENT_PDF_FILENAME)


def a_target_blank_form_post_is_captured(ctx: Context) -> None:
    """A POST cannot be re-issued, so the tab the browser opened is the only copy of the file."""
    expect_pdf(ctx, "#blank_form_submit", INLINE_PDF_FILENAME)


def a_popup_that_renders_before_downloading_is_captured(ctx: Context) -> None:
    """The popup is a page before it fetches, so the download is the popup's, not the opener's."""
    expect_pdf(ctx, "#popup_deferred", INLINE_PDF_FILENAME, opened=DEFERRED_POPUP)


def a_popup_with_no_file_fails_inside_its_budget(ctx: Context) -> None:
    attempt = download(ctx, "#popup_html", opened=NEW_TAB_TARGET)
    failure = attempt.result
    assert isinstance(failure, FlowError), f"a plain popup produced {failure.outputs}"
    assert failure.step == "download", failure.step
    ceiling = (declared_timeout_ms(ctx) + SLACK_MS) / 1000
    assert attempt.took <= ceiling, f"took {attempt.took:.3f}s, budget {ceiling}s"
    assert error_message(failure), "the failure carries no message to act on"


SCENARIOS = [
    Scenario(
        "same-tab attachment",
        Section.STEPS,
        a_same_tab_attachment_comes_back_as_bytes,
    ),
    Scenario(
        "popup to inline pdf",
        Section.STEPS,
        a_popup_that_redirects_to_an_inline_pdf_is_captured,
        known_gaps={"camoufox": POPUP_DOWNLOAD_GAP},
    ),
    Scenario(
        "popup to attachment",
        Section.STEPS,
        a_popup_that_redirects_to_an_attachment_is_captured,
    ),
    Scenario(
        "blank link to a file",
        Section.STEPS,
        a_target_blank_link_to_a_file_is_captured,
    ),
    Scenario(
        "blank form post",
        Section.STEPS,
        a_target_blank_form_post_is_captured,
        known_gaps={"camoufox": POPUP_DOWNLOAD_GAP},
    ),
    Scenario(
        "popup renders then fetches",
        Section.STEPS,
        a_popup_that_renders_before_downloading_is_captured,
        known_gaps={"camoufox": POPUP_DOWNLOAD_GAP},
    ),
    Scenario(
        "popup with no file",
        Section.STEPS,
        a_popup_with_no_file_fails_inside_its_budget,
    ),
]
