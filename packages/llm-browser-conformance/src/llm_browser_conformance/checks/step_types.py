"""One scenario per step type, and per field a step type declares.

Where ``checks/steps.py`` asks whether a driver survives a hostile page, these
ask the flatter question: does the step the YAML describes do what the field
names say it does — the load state ``goto`` waits for, the depth ``dom``
truncates at, the pause ``scroll`` keeps between ticks. Every one of them is
driven as a flow, because that is the surface a caller writes.
"""

import asyncio
import concurrent.futures
import datetime
import decimal
import tempfile
import time
from pathlib import Path
from typing import Any

from llm_browser.flow_pipeline import resolve_flow_text
from llm_browser.flow_repository import FileFlowRepository, FlowRepository
from llm_browser.flows import load_flow_document, load_flow_text, run_flow
from llm_browser.models import FlowSuccess
from llm_browser.results import BytesResult
from pydantic import ValidationError

from llm_browser_conformance.checks.support import (
    error_message,
    expect_failure,
    expect_success,
    one_text,
    texts,
    wrote_nothing,
)
from llm_browser_conformance.scenario import (
    FLOWS_DIR,
    POLL_MS,
    SLACK_MS,
    TIMEOUT_MS,
    Context,
    Scenario,
    Section,
    raises,
)

SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"

PNG_MAGIC = b"\x89PNG"

# What `flows/rows-attributes` reads off `site/rows-attributes.html`.
ATTRIBUTE_ROWS = [
    {"text": "Alpha", "qty": "7", "row_id": "row-1", "href": "/alpha.html"},
    {"text": "Beta", "qty": "8", "row_id": "row-2", "href": "/beta.html"},
    {"text": "Gamma", "qty": "9", "row_id": "row-3", "href": "/gamma.html"},
]

# What `flows/read-properties` reads off the same page.
PROPERTY_ROWS = [
    {"text": name, "tag": "LI", "children": "3", "href": f"/{name.lower()}.html"}
    for name in ("Alpha", "Beta", "Gamma")
]

# What `flows/think.yaml` declares.
THINK_MIN_MS = 400
THINK_MAX_MS = 600

# What `flows/scroll.yaml` declares.
SCROLL_DELTA_PX = 300
SCROLL_TIMES = 3
SCROLL_PAUSE_MIN_MS = 150
# A wheel tick is not promised to land on the pixel, only on the distance.
SCROLL_TOLERANCE_PX = 60
# Far enough past the viewport edge that no widget is under the pointer.
OFF_PAGE_MARGIN_PX = 50

# What `flows/type-delay.yaml` declares.
TYPED_TEXT = "abcde"
TYPE_DELAY_MS = 60
# The lower bound `flows/type-delay-jitter.yaml` declares.
TYPE_DELAY_MIN_MS = 40


def png_size(data: bytes) -> tuple[int, int]:
    """Width and height off a PNG's IHDR — enough to tell a crop from a page."""
    return (
        int.from_bytes(data[16:20], "big"),
        int.from_bytes(data[20:24], "big"),
    )


def resolved_document(text: str, repository: FlowRepository) -> dict[str, Any]:
    """Resolution is async, and Playwright's sync API already owns a running
    loop on this thread, so ``asyncio.run`` gets a thread of its own."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, resolve_flow_text(text, repository)).result()


def goto_waits_for_the_load_state_it_was_asked_for(ctx: Context) -> None:
    """The page's ``load`` handler only runs once a resource the server sits on
    for ``?delay=`` has landed, so the marker is the load state made visible."""
    slow_page = ctx.url("slow-image.html")
    early = expect_success(
        ctx,
        "never.html",
        "goto-wait-until",
        url=slow_page,
        wait_until="domcontentloaded",
    )
    assert texts(early, "marker") == [], "goto waited for load anyway"

    outputs: dict[str, object] = {}
    took = ctx.elapsed(
        lambda: outputs.update(
            expect_success(
                ctx, "never.html", "goto-wait-until", url=slow_page, wait_until="load"
            )
        )
    )
    assert one_text(outputs, "marker") == "loaded"
    assert took >= ctx.delay_ms / 1000, f"load returned after {took:.3f}s"


def goto_refuses_a_url_that_is_not_http(ctx: Context) -> None:
    failure = expect_failure(ctx, "never.html", "goto-scheme")
    assert failure.step == "goto"
    assert getattr(failure.data, "error", None) == "ValueError"
    message = error_message(failure)
    assert "http or https" in message, message


def every_screenshot_step_returns_png_bytes(ctx: Context) -> None:
    """With a ``path:`` or without one, a screenshot step returns the PNG, and
    a ``selector:`` crops it to that element.

    ``path:`` is an instruction to the CLI — the runner has to leave it alone.
    """
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "shot.png"
        with wrote_nothing(ctx):
            try:
                outputs = expect_success(
                    ctx, "form.html", "screenshot", path=str(target)
                )
            except NotImplementedError as exc:
                raise ctx.skip(str(exc)) from exc
        assert not target.exists(), "`path:` is CLI-only; the runner wrote a file"
    for step in ("explicit", "session", "element"):
        shot = outputs[step]
        assert isinstance(shot, BytesResult), shot
        assert shot.content.startswith(PNG_MAGIC), shot.content[:16]
        assert shot.media_type == "image/png"
        assert shot.name == f"{step}.png"
    page = outputs["session"]
    element = outputs["element"]
    assert isinstance(page, BytesResult) and isinstance(element, BytesResult)
    assert png_size(element.content) < png_size(page.content), (
        f"`selector:` captured {png_size(element.content)}, "
        f"the page is {png_size(page.content)}"
    )


def read_pulls_a_different_attribute_per_field(ctx: Context) -> None:
    """``path:`` is an instruction to the CLI — the runner has to leave it
    alone and hand the rows back instead."""
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "rows.json"
        with wrote_nothing(ctx):
            outputs = expect_success(
                ctx, "rows-attributes.html", "read-attributes", path=str(target)
            )
        assert not target.exists(), "`path:` is CLI-only; the runner wrote a file"
    assert outputs["rows"] == ATTRIBUTE_ROWS


def parse_coerces_every_cell_to_its_declared_type(ctx: Context) -> None:
    outputs = expect_success(
        ctx,
        "parse-table.html",
        "parse-table",
        schema_path=str(SCHEMAS_DIR / "table-row.yaml"),
    )
    rows: Any = outputs["typed"]
    assert [row["name"] for row in rows] == ["widget", "gadget"]
    first = rows[0]
    assert first["qty"] == 7 and isinstance(first["qty"], int)
    assert first["price"] == decimal.Decimal("19.95")
    assert first["due"] == datetime.date(2024, 3, 5)
    assert first["note"] is None, "the missing column kept its declared default"


def dom_truncates_at_max_depth(ctx: Context) -> None:
    """``path:`` is an instruction to the CLI — the runner has to leave it
    alone and hand the snippet back instead."""
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "tree.html"
        with wrote_nothing(ctx):
            outputs = expect_success(
                ctx, "nested-tree.html", "dom-depth", path=str(target)
            )
        assert not target.exists(), "`path:` is CLI-only; the runner wrote a file"
    shallow = str(outputs["shallow"])
    whole = str(outputs["whole"])
    assert "level-1" in shallow, shallow
    assert "deep-leaf" not in shallow, shallow
    assert "deep-leaf" in whole, whole


def think_sleeps_inside_the_window_it_declares(ctx: Context) -> None:
    took = ctx.elapsed(lambda: expect_success(ctx, "never.html", "think"))
    assert took >= THINK_MIN_MS / 1000, f"returned after {took:.3f}s"
    ceiling = (THINK_MAX_MS + SLACK_MS) / 1000
    assert took <= ceiling, f"took {took:.3f}s, budget {ceiling}s"


def settled_scroll_y(ctx: Context) -> float:
    """Chromium animates a wheel tick, so the last one is still in flight when
    the step returns; the read waits for the number to hold still."""
    previous = -1.0
    deadline = time.monotonic() + TIMEOUT_MS / 1000
    while time.monotonic() < deadline:
        current = float(ctx.js("window.scrollY"))
        if current == previous:
            return current
        previous = current
        time.sleep(POLL_MS / 1000)
    return previous


def park_pointer_off_the_page(ctx: Context) -> None:
    """Put the pointer where a freshly opened tab leaves it: outside the page.

    The whole suite shares one session, and a click moves the pointer and
    leaves it there — across navigations — so a scroll scenario that did not
    say where the pointer is would answer a different question depending on
    which scenarios ran before it.
    """
    mouse = getattr(ctx.session.get_page(), "mouse", None)
    if mouse is None:  # nodriver has no page-level mouse, and skips scroll anyway
        return
    width, height = ctx.js("[window.innerWidth, window.innerHeight]")
    mouse.move(width + OFF_PAGE_MARGIN_PX, height + OFF_PAGE_MARGIN_PX)


def scroll_moves_the_page_one_tick_at_a_time(ctx: Context) -> None:
    """``scroll`` is asked to move a page nothing has pointed at yet, which is
    what a caller who has just opened one has."""

    def run_it() -> None:
        try:
            expect_success(ctx, "tall.html", "scroll")
        except NotImplementedError as exc:
            raise ctx.skip(str(exc)) from exc

    park_pointer_off_the_page(ctx)
    took = ctx.elapsed(run_it)
    scrolled = settled_scroll_y(ctx)
    expected = SCROLL_TIMES * SCROLL_DELTA_PX
    assert abs(scrolled - expected) <= SCROLL_TOLERANCE_PX, f"scrolled {scrolled}px"
    # The pause is between ticks, not after the last one.
    floor = (SCROLL_TIMES - 1) * SCROLL_PAUSE_MIN_MS / 1000
    assert took >= floor, f"three ticks took {took:.3f}s"


def an_eval_only_step_mutates_the_page(ctx: Context) -> None:
    outputs = expect_success(ctx, "pick-list.html", "eval-step")
    assert one_text(outputs, "result") == "mutated"


def pick_clicks_the_item_whose_text_matches(ctx: Context) -> None:
    """The list has three items on purpose: ``pick`` short-circuits a single
    match without looking at ``value``, which would prove nothing."""
    outputs = expect_success(ctx, "pick-list.html", "pick")
    assert one_text(outputs, "result") == "Beta"

    failure = expect_failure(ctx, "pick-list.html", "pick-missing")
    assert failure.step == "pick"
    assert "Delta" in error_message(failure)


def type_delay_sends_one_keydown_per_character(ctx: Context) -> None:
    outputs: dict[str, object] = {}
    took = ctx.elapsed(
        lambda: outputs.update(expect_success(ctx, "keydown-count.html", "type-delay"))
    )
    assert one_text(outputs, "value") == TYPED_TEXT
    assert one_text(outputs, "keydowns") == str(len(TYPED_TEXT))
    floor = len(TYPED_TEXT) * TYPE_DELAY_MS / 1000
    assert took >= floor, f"typing {TYPED_TEXT!r} took {took:.3f}s"


def a_jittered_delay_still_sends_one_keydown_per_character(ctx: Context) -> None:
    """`delay: [min, max]` is a cadence, not a licence to drop keys: the page
    must still see one keydown per character, no faster than the floor."""
    outputs: dict[str, object] = {}
    took = ctx.elapsed(
        lambda: outputs.update(
            expect_success(ctx, "keydown-count.html", "type-delay-jitter")
        )
    )
    assert one_text(outputs, "value") == TYPED_TEXT
    assert one_text(outputs, "keydowns") == str(len(TYPED_TEXT))
    floor = len(TYPED_TEXT) * TYPE_DELAY_MIN_MS / 1000
    assert took >= floor, f"typing {TYPED_TEXT!r} took {took:.3f}s"


def a_humanized_click_step_is_still_a_trusted_event(ctx: Context) -> None:
    """`humanize: true` changes the pointer's path, not its provenance — a
    curve that arrives as an untrusted event buys nothing."""
    expect_success(ctx, "form.html", "humanize-click")
    assert ctx.trusted("#reveal") == "true"


def a_chord_selects_the_field_before_the_replacement(ctx: Context) -> None:
    outputs = expect_success(ctx, "keydown-count.html", "press-chord")
    assert one_text(outputs, "value") == "new"


def a_dispatched_click_step_is_reported_untrusted(ctx: Context) -> None:
    expect_success(ctx, "form.html", "dispatch-click")
    assert ctx.trusted("#reveal") == "false"


def an_embedded_sub_flow_reports_its_output_qualified(ctx: Context) -> None:
    outputs = expect_success(ctx, "rows-attributes.html", "run-flow-embedded")
    assert one_text(outputs, "child/read") == "Beta"


def a_sub_flow_reference_is_resolved_through_a_repository(ctx: Context) -> None:
    text = (FLOWS_DIR / "run-flow-ref.yaml").read_text()
    unresolved = raises(ValidationError, lambda: load_flow_text(text))
    assert "FlowRepository" in str(unresolved), str(unresolved)

    repository = FileFlowRepository(FLOWS_DIR)
    document = resolved_document(text, repository)
    flow = load_flow_document(document)
    ctx.visit("rows-attributes.html")
    result = run_flow(ctx.session, flow, {})
    assert isinstance(result, FlowSuccess), result
    assert result.outputs["child/read"] == [{"text": "Gamma"}]


def dom_returns_the_body_as_one_element(ctx: Context) -> None:
    """`<body>` outerHTML is several elements with a wrapper around them, and
    the wrapper is what the caller asked for."""
    outputs = expect_success(ctx, "body-fragment.html", "dom-body")
    whole = str(outputs["whole"])
    assert whole.startswith("<body"), whole[:80]
    assert "outerHTML is several elements" in whole, whole[:200]
    assert "<script" not in whole, whole
    assert 'href="/next.html"' in whole, whole[:200]

    stripped = str(outputs["stripped"])
    assert "href=" not in stripped, stripped[:200]


def a_dom_step_fails_below_its_min_chars(ctx: Context) -> None:
    failure = expect_failure(ctx, "body-fragment.html", "dom-body-min-chars")
    assert failure.step == "whole"
    assert "Expected \u2265100000 chars" in error_message(failure)


def a_read_step_fails_below_its_minimums(ctx: Context) -> None:
    """A page still hydrating answers with nothing and looks successful."""
    outputs = expect_success(ctx, "rows-attributes.html", "read-minimums")
    assert texts(outputs, "rows") == ["Alpha", "Beta", "Gamma"]

    failure = expect_failure(ctx, "rows-attributes.html", "read-minimums-short")
    assert failure.step == "rows"
    assert "Expected \u22659 rows, got 3" in error_message(failure)


def a_parse_step_fails_below_its_minimums(ctx: Context) -> None:
    """`parse` is "like `read`", minimums included."""
    schema = str(SCHEMAS_DIR / "table-row.yaml")
    outputs = expect_success(
        ctx, "parse-table.html", "parse-minimums", schema_path=schema
    )
    typed: Any = outputs["typed"]
    assert len(typed) == 2

    failure = expect_failure(
        ctx, "parse-table.html", "parse-minimums-short", schema_path=schema
    )
    assert failure.step == "typed"
    assert "Expected \u22659 rows, got 2" in error_message(failure)


def read_pulls_dom_properties_alongside_attributes(ctx: Context) -> None:
    outputs = expect_success(ctx, "rows-attributes.html", "read-properties")
    assert outputs["rows"] == PROPERTY_ROWS


SCENARIOS = [
    Scenario(
        "goto wait_until",
        Section.STEPS,
        goto_waits_for_the_load_state_it_was_asked_for,
        covers=frozenset({"step:goto", "field:goto.wait_until"}),
        known_gaps={
            "nodriver": "goto drops wait_until: NodriverDriver.goto calls "
            "tab.get(url), which has no load-state argument, so both wait "
            "states get whatever tab.get itself waits for"
        },
    ),
    Scenario(
        "goto scheme guard",
        Section.STEPS,
        goto_refuses_a_url_that_is_not_http,
        covers=frozenset({"api:goto.scheme_guard"}),
    ),
    Scenario(
        "screenshot step",
        Section.STEPS,
        every_screenshot_step_returns_png_bytes,
        covers=frozenset(
            {
                "step:screenshot",
                "field:screenshot.path",
                "field:screenshot.selector",
                "session:screenshot_bytes",
            }
        ),
    ),
    Scenario(
        "read attributes",
        Section.STEPS,
        read_pulls_a_different_attribute_per_field,
        covers=frozenset(
            {"field:read.extract", "field:read.path", "session:parse_elements"}
        ),
    ),
    Scenario(
        "parse typed rows",
        Section.STEPS,
        parse_coerces_every_cell_to_its_declared_type,
        covers=frozenset(
            {
                "step:parse",
                "field:parse.selector",
                "field:parse.schema_path",
            }
        ),
    ),
    Scenario(
        "dom step depth",
        Section.STEPS,
        dom_truncates_at_max_depth,
        covers=frozenset(
            {
                "step:dom",
                "field:dom.selector",
                "field:dom.max_depth",
                "field:dom.path",
                "session:dom",
            }
        ),
    ),
    Scenario(
        "dom body",
        Section.STEPS,
        dom_returns_the_body_as_one_element,
        covers=frozenset({"field:dom.level"}),
    ),
    Scenario(
        "dom min_chars",
        Section.STEPS,
        a_dom_step_fails_below_its_min_chars,
        covers=frozenset({"field:dom.min_chars"}),
    ),
    Scenario(
        "read minimums",
        Section.STEPS,
        a_read_step_fails_below_its_minimums,
        covers=frozenset({"field:read.min_chars", "field:read.min_rows"}),
    ),
    Scenario(
        "parse minimums",
        Section.STEPS,
        a_parse_step_fails_below_its_minimums,
        covers=frozenset({"field:parse.min_chars", "field:parse.min_rows"}),
    ),
    Scenario(
        "read properties",
        Section.STEPS,
        read_pulls_dom_properties_alongside_attributes,
    ),
    Scenario(
        "think pauses",
        Section.STEPS,
        think_sleeps_inside_the_window_it_declares,
        covers=frozenset({"step:think", "field:think.min_ms", "field:think.max_ms"}),
    ),
    Scenario(
        "wheel ticks",
        Section.STEPS,
        scroll_moves_the_page_one_tick_at_a_time,
        covers=frozenset(
            {
                "step:scroll",
                "field:scroll.delta",
                "field:scroll.times",
                "field:scroll.pause",
                "session:scroll",
            }
        ),
    ),
    Scenario(
        "eval step",
        Section.STEPS,
        an_eval_only_step_mutates_the_page,
        covers=frozenset({"step:eval", "option:eval"}),
    ),
    Scenario(
        "pick by text",
        Section.STEPS,
        pick_clicks_the_item_whose_text_matches,
        covers=frozenset(
            {
                "step:pick",
                "field:pick.selector",
                "field:pick.value",
                "session:pick",
                "session:find_all",
            }
        ),
    ),
    Scenario(
        "type delay",
        Section.STEPS,
        type_delay_sends_one_keydown_per_character,
        covers=frozenset({"field:type.delay", "field:type.selector"}),
    ),
    Scenario(
        "jittered key delay",
        Section.STEPS,
        a_jittered_delay_still_sends_one_keydown_per_character,
        covers=frozenset(
            {"api:type.delay_jitter", "field:type.delay", "field:type.humanize"}
        ),
    ),
    Scenario(
        "humanized click step",
        Section.STEPS,
        a_humanized_click_step_is_still_a_trusted_event,
        covers=frozenset({"field:click.humanize"}),
    ),
    Scenario(
        "press chord",
        Section.STEPS,
        a_chord_selects_the_field_before_the_replacement,
        covers=frozenset({"field:press.selector"}),
    ),
    Scenario(
        "dispatch click step",
        Section.STEPS,
        a_dispatched_click_step_is_reported_untrusted,
        covers=frozenset({"field:click.dispatch"}),
        known_gaps={
            "camoufox": "Gecko marks an event dispatched from Playwright's "
            "chrome-privileged agent as trusted, so dispatch=True is "
            "indistinguishable from real input on Firefox"
        },
    ),
    Scenario(
        "run-flow embedded",
        Section.STEPS,
        an_embedded_sub_flow_reports_its_output_qualified,
        covers=frozenset(
            {
                "step:run-flow",
                "field:run-flow.flow",
                "field:run-flow.data",
                "api:outputs.qualified_name",
            }
        ),
    ),
    Scenario(
        "run-flow from a repository",
        Section.STEPS,
        a_sub_flow_reference_is_resolved_through_a_repository,
        covers=frozenset({"api:flow_repository"}),
    ),
]
