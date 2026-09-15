"""Downloads the page hands to a tab the session never opened.

A portal that prints a receipt rarely writes the file into the tab you are
driving: a button calls ``window.open`` on an ``.action`` URL, that tab
redirects to the PDF, and the browser turns it into a download. A
``target=_blank`` link and a ``target=_blank`` form post are the same shape
with less JavaScript.

Most of those still reach the caller, because a popup that never commits a
document leaves the browser reporting the download on the opener — the one
page ``download_bytes`` listens on. The row that does not is ``popup
renders then fetches``: that popup is a document before it asks for the file,
so the download belongs to a page of its own and the step times out with the
receipt sitting in the Downloads folder. That is the shape that broke a real
run; the others are here so that the day a driver starts listening
context-wide, the table says which shapes changed.
"""

from llm_browser.flows import run_flow
from llm_browser.models import FlowError, FlowSuccess
from llm_browser.results import BytesResult

from llm_browser_conformance.checks.session_api import tabs_closed_after
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

# What `flows/popup-download.yaml` declares.
DOWNLOAD_TIMEOUT_MS = 4_000

# One reason for every row that fails for it; the issue number lands here.
POPUP_DOWNLOAD_GAP = (
    "download_bytes listens on the page the trigger was clicked on, so a file "
    "the browser delivers to another tab is never seen: see #40"
)


def download(ctx: Context, selector: str) -> FlowSuccess | FlowError:
    """Click ``selector`` and hand back the flow's verdict, one tab again.

    The opener is read before the click on purpose: afterwards the newest tab
    may be the popup, and the cleanup would then close the page every later
    scenario runs on.
    """
    ctx.visit(PAGE)
    opener = ctx.session.get_page()
    with tabs_closed_after(ctx, opener):
        try:
            result = run_flow(ctx.session, ctx.flow(FLOW), {"selector": selector})
        except NotImplementedError as exc:
            raise ctx.skip(str(exc)) from exc
    assert isinstance(result, FlowSuccess | FlowError), result
    return result


def expect_pdf(ctx: Context, selector: str, filename: str) -> None:
    result = download(ctx, selector)
    assert isinstance(result, FlowSuccess), f"{result.step}: {result.data}"
    payload = result.outputs["download"]
    assert isinstance(payload, BytesResult), payload
    assert payload.content.startswith(PDF_MAGIC), payload.content[:16]
    assert payload.name == filename, payload.name


def a_same_tab_attachment_comes_back_as_bytes(ctx: Context) -> None:
    """The baseline the other rows are measured against: the response the
    click starts lands in the tab the click happened in."""
    expect_pdf(ctx, "#attach", ATTACHMENT_PDF_FILENAME)


def a_popup_that_redirects_to_an_inline_pdf_is_captured(ctx: Context) -> None:
    """``Content-Disposition: inline`` is not a request to download, but a
    headless browser has no viewer to show it in, so it downloads anyway —
    which is exactly how the receipt reaches a Downloads folder instead of the
    caller."""
    expect_pdf(ctx, "#popup_inline", INLINE_PDF_FILENAME)


def a_popup_that_redirects_to_an_attachment_is_captured(ctx: Context) -> None:
    expect_pdf(ctx, "#popup_attach", ATTACHMENT_PDF_FILENAME)


def a_target_blank_link_to_a_file_is_captured(ctx: Context) -> None:
    expect_pdf(ctx, "#blank_link", ATTACHMENT_PDF_FILENAME)


def a_target_blank_form_post_is_captured(ctx: Context) -> None:
    """A POST cannot be re-issued from the outside — no url to fetch again —
    so the tab the browser opened for it is the only copy of the file."""
    expect_pdf(ctx, "#blank_form_submit", INLINE_PDF_FILENAME)


def a_popup_that_renders_before_downloading_is_captured(ctx: Context) -> None:
    """The one that broke a real run: the popup is a page for a moment before
    it asks for the file, so the download is the popup's, not the opener's."""
    expect_pdf(ctx, "#popup_deferred", INLINE_PDF_FILENAME)


def a_popup_with_no_file_fails_inside_its_budget(ctx: Context) -> None:
    """The negative case, and the one a caller feels first: a trigger that
    opens an ordinary page must report that no download arrived, inside the
    budget the step declared, rather than hang."""
    result: list[FlowSuccess | FlowError] = []
    took = ctx.elapsed(lambda: result.append(download(ctx, "#popup_html")))
    failure = result[0]
    assert isinstance(failure, FlowError), f"a plain popup produced {failure.outputs}"
    assert failure.step == "download", failure.step
    ceiling = (DOWNLOAD_TIMEOUT_MS + 2 * SLACK_MS) / 1000
    assert took <= ceiling, f"took {took:.3f}s, budget {ceiling}s"
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
        known_gaps={
            "patchright": POPUP_DOWNLOAD_GAP,
            "camoufox": POPUP_DOWNLOAD_GAP,
        },
    ),
    Scenario(
        "popup with no file",
        Section.STEPS,
        a_popup_with_no_file_fails_inside_its_budget,
    ),
]
