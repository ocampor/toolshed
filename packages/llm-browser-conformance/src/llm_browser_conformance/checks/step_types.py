import asyncio
import concurrent.futures
import datetime
import decimal
import tempfile
import time
from pathlib import Path
from typing import Any

from llm_browser.behavior import Behavior
from llm_browser.flow_pipeline import resolve_flow_text
from llm_browser.flow_repository import FileFlowRepository, FlowRepository
from llm_browser.flows import load_flow_document, load_flow_text, run_flow
from llm_browser.models import FlowSuccess
from llm_browser.results import BytesResult
from pydantic import ValidationError

from llm_browser_conformance.checks.support import (
    error_message,
    expect_failure,
    expect_flow_success,
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
ROW_NAMES = ("Alpha", "Beta", "Gamma")
PROPERTY_ROWS = [
    {"text": name, "tag": "LI", "children": "3", "href": f"/{name.lower()}.html"}
    for name in ROW_NAMES
]
BARE_ROWS = [{"text": name} for name in ROW_NAMES]

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
    return (
        int.from_bytes(data[16:20], "big"),
        int.from_bytes(data[20:24], "big"),
    )


def resolved_document(text: str, repository: FlowRepository) -> dict[str, Any]:
    """Playwright's sync API owns this thread's loop, so ``asyncio.run`` gets its own thread."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, resolve_flow_text(text, repository)).result()


def goto_waits_for_the_load_state_it_was_asked_for(ctx: Context) -> None:
    """The ``load`` handler runs only after the ``?delay=`` resource lands, so the marker is the load state."""
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
    """Chromium animates a wheel tick, so the read waits for the number to hold still."""
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
    """One session is shared and a click leaves the pointer where it was, so each scroll test parks it first."""
    mouse = getattr(ctx.session.get_page(), "mouse", None)
    if mouse is None:  # nodriver has no page-level mouse, and skips scroll anyway
        return
    width, height = ctx.js("[window.innerWidth, window.innerHeight]")
    mouse.move(width + OFF_PAGE_MARGIN_PX, height + OFF_PAGE_MARGIN_PX)


def scroll_moves_the_page_one_tick_at_a_time(ctx: Context) -> None:
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
    """Three items on purpose: ``pick`` short-circuits a single match without reading ``value``."""
    outputs = expect_success(ctx, "pick-list.html", "pick")
    assert one_text(outputs, "result") == "Beta"

    failure = expect_failure(ctx, "pick-list.html", "pick-missing")
    assert failure.step == "pick"
    assert "Delta" in error_message(failure)


def timed_typing(ctx: Context, flow_name: str) -> tuple[float, dict[str, object]]:
    """Times the ``type`` step alone: the opening navigation costs more than any per-key floor."""
    ctx.visit("keydown-count.html")
    flow = ctx.flow(flow_name)
    typing, reading = flow.steps[:1], flow.steps[1:]
    assert typing[0].name == "type", f"{flow_name} must open with the type step"
    took = ctx.elapsed(
        lambda: expect_flow_success(ctx, flow.model_copy(update={"steps": typing}))
    )
    return took, expect_flow_success(ctx, flow.model_copy(update={"steps": reading}))


def assert_typed_at_least(
    took: float, outputs: dict[str, object], floor_ms: int
) -> None:
    assert one_text(outputs, "value") == TYPED_TEXT
    assert one_text(outputs, "keydowns") == str(len(TYPED_TEXT))
    floor = len(TYPED_TEXT) * floor_ms / 1000
    assert took >= floor, f"typing {TYPED_TEXT!r} took {took:.3f}s"


def type_delay_sends_one_keydown_per_character(ctx: Context) -> None:
    took, outputs = timed_typing(ctx, "type-delay")
    assert_typed_at_least(took, outputs, TYPE_DELAY_MS)


def a_jittered_delay_still_sends_one_keydown_per_character(ctx: Context) -> None:
    took, outputs = timed_typing(ctx, "type-delay-jitter")
    assert_typed_at_least(took, outputs, TYPE_DELAY_MIN_MS)


def a_humanized_step_drives_the_element_with_trusted_input(ctx: Context) -> None:
    """`humanize: true` changes the path and keystrokes, not their provenance; a plain fill sends no keydown."""
    expect_success(ctx, "form.html", "humanize")
    assert ctx.trusted("#reveal") == "true"
    assert ctx.trusted("#name") == "true"
    assert ctx.js("document.querySelector('#name').value") == "typed"


def a_run_level_behavior_humanizes_a_step_that_says_nothing(ctx: Context) -> None:
    ctx.visit("keydown-count.html")
    result = run_flow(
        ctx.session, ctx.flow("run-behavior"), {}, behavior=Behavior.human()
    )
    assert isinstance(result, FlowSuccess), f"{result.step}: {result.data}"
    assert result.behavior == "human"
    assert one_text(result.outputs, "value") == TYPED_TEXT
    assert one_text(result.outputs, "keydowns") == str(len(TYPED_TEXT))


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
    """`<body>` outerHTML is several elements plus the wrapper the caller asked for."""
    outputs = expect_success(ctx, "body-fragment.html", "dom-body")
    whole = str(outputs["whole"])
    assert whole.startswith("<body"), whole[:80]
    assert "outerHTML is several elements" in whole, whole[:200]
    assert "<script" not in whole, whole
    assert 'href="/next.html"' in whole, whole[:200]

    stripped = str(outputs["stripped"])
    assert "href=" not in stripped, stripped[:200]


def dom_reads_the_first_match_in_document_order(ctx: Context) -> None:
    """A comma list is document order, not priority: `body` wraps `main`."""
    outputs = expect_success(ctx, "body-fragment.html", "dom-body")
    first = str(outputs["first"])
    assert first.startswith("<body"), first[:80]
    assert "<main" in first, first[:200]


def read_exclude_drops_the_text_and_nothing_else(ctx: Context) -> None:
    """Only a browser shows the read uses a detached copy, where `innerText` reads like `textContent`."""
    outputs = expect_success(ctx, "read-exclude.html", "read-exclude")

    whole = one_text(outputs, "whole") or ""
    assert "NEW" in whole, whole
    assert "HIDDEN" not in whole, whole

    pruned = one_text(outputs, "pruned") or ""
    assert "Alpha" in pruned, pruned
    assert "NEW" not in pruned, pruned
    assert "Mexico" not in pruned, pruned
    assert "HIDDEN" in pruned, pruned
    assert "Footnote" not in pruned, pruned

    rows: Any = outputs["pruned"]
    assert rows[0]["country"] == "mx", rows
    assert rows[0]["note"] == "Footnote", rows


def a_saved_read_feeds_the_next_steps_template(ctx: Context) -> None:
    """Row 0 is Alpha, so a save that ignored ``where`` fills the wrong text."""
    expect_success(ctx, "match-rules.html", "save-as")
    assert ctx.value("#target") == "Beta"


def read_pulls_dom_properties_alongside_attributes(ctx: Context) -> None:
    outputs = expect_success(ctx, "rows-attributes.html", "read-properties")
    assert outputs["rows"] == PROPERTY_ROWS
    assert outputs["bare"] == BARE_ROWS


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
        "read exclude",
        Section.STEPS,
        read_exclude_drops_the_text_and_nothing_else,
        covers=frozenset({"field:read.exclude"}),
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
        "dom first match",
        Section.STEPS,
        dom_reads_the_first_match_in_document_order,
        covers=frozenset({"session:dom"}),
    ),
    Scenario(
        "read properties",
        Section.STEPS,
        read_pulls_dom_properties_alongside_attributes,
    ),
    Scenario(
        "read save_as",
        Section.STEPS,
        a_saved_read_feeds_the_next_steps_template,
        covers=frozenset({"field:read.save_as"}),
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
        "humanized click and fill",
        Section.STEPS,
        a_humanized_step_drives_the_element_with_trusted_input,
        covers=frozenset({"field:click.humanize", "field:fill.humanize"}),
    ),
    Scenario(
        "run-level behavior",
        Section.STEPS,
        a_run_level_behavior_humanizes_a_step_that_says_nothing,
        covers=frozenset({"api:run_flow.behavior"}),
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
