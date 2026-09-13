"""The ``BrowserSession`` surface a YAML flow cannot reach.

A flow step covers most of the library, but not all of it: ``probe``,
``screenshot_bytes``, ``element_exists``, ``find_all``, ``latest_tab``,
``wait_for_load_state``, the sanitize level ``dom`` takes, the humanized
``Behavior`` and the whole attach lifecycle are only reachable by calling the
session. These scenarios call it directly, and hand the session back exactly
as they found it — one browser is shared by every row.
"""

import contextlib
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from concurrent import futures
from pathlib import Path
from typing import Any

from llm_browser.behavior import Behavior
from llm_browser.drivers import resolve_driver
from llm_browser.drivers.base import Driver
from llm_browser.explore_models import ExploreTarget, Intent, Stability, Verdict
from llm_browser.html import SanitizeLevel
from llm_browser.parse import ExtractField
from llm_browser.probe import human_needed
from llm_browser.session import BrowserSession

from llm_browser_conformance.checks.support import artifact_snapshot
from llm_browser_conformance.drivers import chrome_binary, configured
from llm_browser_conformance.scenario import (
    POLL_MS,
    SLACK_MS,
    Context,
    Scenario,
    Section,
    raises,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

MISSING_TIMEOUT_MS = 1_000

# No punctuation: ``type_punct_pause`` would add jitter on top of the per-key
# delay, and the assertion wants the cleanest lower bound it can state.
TYPED_TEXT = "conformance " * 4


# --- probe ---


def probe_sees_the_password_field_and_the_page_text(ctx: Context) -> None:
    ctx.visit("login-wall.html")
    probe = ctx.session.probe()
    assert probe.password_visible is True
    assert probe.challenge is False
    assert "Sign in" in probe.text
    assert human_needed(probe) is True
    # An <input> has no innerText, so the probed element is the submit button.
    scoped = ctx.session.probe("button")
    assert scoped.selector_text is not None
    assert scoped.selector_text.strip() == "Sign in"


def probe_sees_a_visible_bot_challenge(ctx: Context) -> None:
    ctx.visit("api-challenge.html")
    probe = ctx.session.probe()
    assert probe.challenge is True
    assert probe.password_visible is False
    assert human_needed(probe) is True


# --- screenshots ---


def screenshot_bytes_returns_a_png_and_writes_nothing(ctx: Context) -> None:
    ctx.visit("form.html")
    before = artifact_snapshot(ctx.session)
    data = ctx.session.screenshot_bytes()
    assert data.startswith(PNG_MAGIC), data[:16]
    assert len(data) > 1_000, len(data)
    assert artifact_snapshot(ctx.session) == before


# --- finding ---


def element_exists_answers_false_inside_its_timeout(ctx: Context) -> None:
    """The bool is the easy half; the point is that the absent case comes back
    as a value within the budget rather than as a ``TimeoutError``."""
    ctx.visit("form.html")
    assert ctx.session.element_exists("#name") is True
    answers: list[bool] = []
    elapsed = ctx.elapsed(
        lambda: answers.append(
            ctx.session.element_exists("#no-such-element", timeout=MISSING_TIMEOUT_MS)
        )
    )
    assert answers == [False]
    budget = (MISSING_TIMEOUT_MS + POLL_MS + SLACK_MS) / 1000
    assert elapsed <= budget, f"took {elapsed:.3f}s, budget {budget}s"


def find_all_returns_what_find_refuses(ctx: Context) -> None:
    ctx.visit("ambiguous.html")
    locator = ctx.session.find_all(".item")
    assert ctx.session.driver.count(locator) == 2
    error = raises(ValueError, lambda: ctx.session.find(".item"))
    assert "found 2" in str(error), error


def explore_counts_the_whole_list_and_reads_only_the_sample(ctx: Context) -> None:
    """What an author asks before writing the `read`: how many, and saying what."""
    ctx.visit("rows-attributes.html")
    found = ctx.session.explore(
        ".row",
        extract={
            "label": ExtractField(child_selector=".label"),
            "absent": ExtractField(child_selector=".nothing-matches-this"),
        },
        sample=2,
    )
    assert found.count == 3, found
    assert [row["label"] for row in found.sample] == ["Alpha", "Beta"], found
    assert found.empty_fields == ["absent"], found
    assert found.text_chars > 0, found

    missing = ctx.session.explore("#no-such-element", timeout_ms=MISSING_TIMEOUT_MS)
    assert missing.count == 0, missing
    assert missing.sample == [], missing
    assert missing.verdict is Verdict.MISSING, missing
    assert missing.first is None, missing


def explore_says_which_button_a_click_would_miss(ctx: Context) -> None:
    """The question `count` cannot answer: the selector is right, and the
    click still lands on the banner sitting over it."""
    ctx.visit("explore-actionability.html")

    buried = ctx.session.explore("#buried", intent=Intent.CLICK)
    assert buried.verdict is Verdict.NOT_ACTIONABLE, buried
    assert buried.first is not None and buried.first.why_not == ["covered"], buried
    assert buried.first.covered_by is not None, buried
    assert buried.first.covered_by.tag == "div", buried
    # Every proposal the button offers, best first, each checked to match it
    # and nothing else -- `role=` included, which Playwright resolves natively.
    assert buried.candidates == [
        '[data-testid="buy"]',
        'role=button[name="Buy now"]',
        "#buried",
    ], buried
    assert buried.stability is Stability.ID, buried

    off = ctx.session.explore("#off", intent=Intent.CLICK)
    assert off.first is not None and off.first.why_not == ["disabled"], off
    assert off.verdict is Verdict.NOT_ACTIONABLE, off
    # A disabled button is still a fine thing to wait for.
    assert ctx.session.explore("#off", intent=Intent.WAIT).verdict is Verdict.OK, off

    clear = ctx.session.explore("#clear", intent=Intent.CLICK)
    assert clear.first is not None and clear.first.clickable, clear
    assert clear.verdict is Verdict.OK, clear
    assert clear.since_navigation_ms is not None, clear

    both = ctx.session.explore("button[data-testid]", intent=Intent.CLICK)
    assert both.count == 2 and both.verdict is Verdict.AMBIGUOUS, both


def explore_reads_what_a_loose_click_would_cost(ctx: Context) -> None:
    """Below the fold is not an obstacle, a label is not covered by its own
    checkbox, and a card that swallows a dismiss button says so."""
    ctx.visit("explore-actionability.html")

    # `disabled` on the fieldset, nothing on the input: only `:disabled` sees it.
    in_fieldset = ctx.session.explore("#in-fieldset", intent=Intent.FILL)
    assert in_fieldset.first is not None, in_fieldset
    assert in_fieldset.first.enabled is False, in_fieldset
    assert in_fieldset.first.why_not == ["disabled"], in_fieldset
    assert in_fieldset.verdict is Verdict.NOT_ACTIONABLE, in_fieldset

    sizeless = ctx.session.explore("#sizeless", intent=Intent.CLICK)
    assert sizeless.first is not None and not sizeless.first.visible, sizeless
    assert sizeless.first.why_not == ["hidden"], sizeless
    # No box to hit-test: `covered_by` is "not asked", not "nothing over it".
    assert not sizeless.first.hit_tested, sizeless
    assert sizeless.first.covered_by is None, sizeless

    tick = ctx.session.explore("#tick", intent=Intent.CLICK)
    assert tick.first is not None and tick.first.covered_by is None, tick
    assert tick.verdict is Verdict.OK, tick

    card = ctx.session.explore("#card", intent=Intent.CLICK)
    assert card.first is not None, card
    assert [c.text for c in card.first.nested_controls] == ["Not Interested"], card
    # `main` is at the centre of the card -- an ancestor showing through a gap
    # in the anchor's own box, not something painted over it.
    assert card.first.covered_by is None, card
    # The test id on the card outranks everything else it could be called.
    assert card.candidates[0] == '[data-testid="mission"]', card
    assert len(card.candidates) <= 3, card
    assert card.since_navigation_ms is not None, card
    assert card.since_call_ms is not None, card

    # Last, because the scroll it takes outlives the call: every match read
    # after it would be `offscreen` too.
    below = ctx.session.explore("#below", intent=Intent.CLICK)
    assert below.first is not None and below.first.why_not == ["offscreen"], below
    assert below.first.clickable and below.verdict is Verdict.OK, below
    # Exploring scrolled it into view to hit-test it, and found nothing over it.
    assert below.first.hit_tested and below.first.covered_by is None, below


def explore_many_answers_every_target_in_one_page_call(ctx: Context) -> None:
    """A page's worth of selectors for the price of one wait: the counts, the
    samples and the first-match reads all come back together."""
    ctx.visit("explore-actionability.html")

    started = time.monotonic()
    cards, button, gone, refused = ctx.session.explore_many(
        [
            ExploreTarget(
                selector="article.tile",
                extract={"title": ExtractField(child_selector="h3")},
            ),
            ExploreTarget(selector="#clear", intent=Intent.CLICK),
            ExploreTarget(selector="#no-such-element"),
            # A dangling combinator: Chromium auto-closes an unclosed bracket,
            # but nothing makes this a selector.
            ExploreTarget(selector="div >"),
        ],
        timeout_ms=MISSING_TIMEOUT_MS,
    )
    elapsed = time.monotonic() - started

    assert [row["title"] for row in cards.sample] == ["Alpha", "Bravo", "Charlie"], (
        cards
    )
    assert cards.count == 3 and cards.verdict is Verdict.OK, cards
    # The cards are named only by the build's numbering, so the section around
    # them is what a selector can be written against.
    assert cards.candidates == ['[data-testing-id="deck"] :is(article)'], cards
    assert cards.since_navigation_ms is not None, cards

    assert button.count == 1 and button.verdict is Verdict.OK, button
    assert button.first is not None and button.first.clickable, button

    assert gone.count == 0 and gone.verdict is Verdict.MISSING, gone
    assert gone.first is None and gone.candidates == [], gone

    # A selector the page cannot parse costs its own answer, not the batch's.
    assert refused.error == "not css" and refused.count == 0, refused
    assert refused.verdict is Verdict.MISSING and refused.first is None, refused
    # One wait for the batch, not one per target: the missing selector never
    # spends a timeout of its own, because the others were there.
    budget = (MISSING_TIMEOUT_MS + SLACK_MS) / 1000
    assert elapsed <= budget, f"took {elapsed:.3f}s, budget {budget}s"


def survey_reads_what_the_page_is_made_of(ctx: Context) -> None:
    """The call before the first selector: what is named, what repeats, and
    what the links point at — without touching the page."""
    ctx.visit("explore-actionability.html")

    found = ctx.session.survey()

    named = {mark.selector for mark in found.landmarks}
    assert '[data-testing-id="deck"]' in named, found.landmarks
    assert '[data-testid="buy"]' in named, found.landmarks
    # Test ids first: an author reading the top of the list reads the sturdiest
    # selectors the page offers.
    assert found.landmarks[0].selector.startswith("[data-test"), found.landmarks

    # Every count is page-wide, whatever named it: two elements answer to the
    # pager's label, and saying `1` would promise a step that is ambiguous.
    pagers = [
        mark for mark in found.landmarks if mark.selector == '[aria-label="Pager"]'
    ]
    assert [mark.count for mark in pagers] == [2], found.landmarks

    tiles = [run for run in found.repeats if run.selector == "article.tile"]
    assert [run.count for run in tiles] == [3], found.repeats
    assert [control.text for control in tiles[0].nested_controls] == ["Save"], tiles
    assert not found.truncated, found

    missions = [shape for shape in found.link_shapes if shape.shape == "/missions/<id>"]
    assert [shape.count for shape in missions] == [2], found.link_shapes
    assert missions[0].selector == 'a[href^="/missions/"]', missions

    assert found.hydration.ready_state == "complete", found.hydration
    assert found.hydration.since_navigation_ms > 0, found.hydration
    assert found.title == "Buttons a click would miss", found


# --- tabs ---

TAB_CLOSE_TIMEOUT_S = 5.0

NEW_TAB_TARGET = "new-tab-target.html"


def latest_tab_url(ctx: Context, expected: str, timeout_s: float = 5.0) -> str:
    """Poll the newest tab for its url, asking the page rather than the driver.

    A new tab does not exist the instant the click returns, and on the
    Playwright family the popup only lands in the context once a round trip
    pumps the connection — ``page_url`` reads a cached attribute, so a loop
    built on it would spin out its whole timeout against a stale tab list.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        url = str(ctx.session.evaluate(ctx.session.latest_tab(), "location.href"))
        if expected in url or time.monotonic() >= deadline:
            return url
        time.sleep(0.2)


def require_latest_tab(ctx: Context) -> None:
    """Skip before opening a tab this driver would give no way to close again.

    Decided up front, never from the cleanup: a skip raised once the scenario
    has already passed its assertions reports the wrong outcome, and one
    raised from a ``finally`` swallows the failure it was cleaning up after.
    """
    try:
        ctx.session.latest_tab()
    except NotImplementedError as exc:
        raise ctx.skip(str(exc)) from exc


def close_tab(ctx: Context, tab: Any, opener: Any, deadline: float) -> None:
    """Ask ``tab`` to close and wait for the driver's tab list to drop it.

    The close is deferred onto a timer because a synchronous ``window.close()``
    destroys the target before it answers the CDP call, and nodriver's sync
    bridge then waits forever on a reply that will never come.
    """
    ctx.session.evaluate(tab, "setTimeout(() => window.close(), 0)")
    while ctx.session.latest_tab() is tab:
        assert time.monotonic() < deadline, "the opened tab never closed"
        # Reading the opener is also the refresh: nodriver only learns that a
        # target is gone while its own event loop runs, and only a driver call
        # makes that happen.
        ctx.session.evaluate(opener, "1")
        time.sleep(0.05)


def close_opened_tabs(ctx: Context, opener: Any, opened: str) -> None:
    """Put the browser back to the single tab ``opener``.

    Test isolation: one browser drives every row of a driver's column, so a
    tab left open is shared state each later scenario inherits — it holds the
    foreground, and a failing step screenshots whatever is in front of it.

    ``opened`` names the page the click opened, because a popup is not in the
    driver's tab list the instant the click returns — the same lag
    ``latest_tab_url`` polls out.
    """
    latest_tab_url(ctx, opened)
    deadline = time.monotonic() + TAB_CLOSE_TIMEOUT_S
    while (extra := ctx.session.latest_tab()) is not opener:
        # The inner wait has its own deadline, but it is skipped whenever
        # ``latest_tab`` hands back something other than the tab just asked to
        # close — without this, that turns into an unbounded retry loop.
        assert time.monotonic() < deadline, "the opened tab never closed"
        close_tab(ctx, extra, opener, deadline)


@contextlib.contextmanager
def tabs_closed_after(ctx: Context, opener: Any, opened: str) -> Iterator[None]:
    """Run a scenario body, then put the browser back to the one tab ``opener``.

    The cleanup has to run on the failing path — that is the path it exists
    for — but a plain ``finally`` lets it *replace* what the body raised, and
    the table only ever shows the newest exception. So a popup that will not
    close would be reported where the scenario's own assertion belongs. The
    body's exception wins; the cleanup's rides along as a note.
    """
    body_failure: BaseException | None = None
    try:
        yield
    except BaseException as failure:
        body_failure = failure
        raise
    finally:
        try:
            close_opened_tabs(ctx, opener, opened)
        except Exception as cleanup_failure:
            if body_failure is None:
                raise
            body_failure.add_note(f"cleanup failed too: {cleanup_failure}")


def latest_tab_reaches_the_tab_the_page_opened(ctx: Context) -> None:
    """The ``new tab`` scenario pins that the session stays on the opener; this
    pins the way back — and then puts the browser back to one tab, since every
    later row inherits whatever this one leaves open."""
    require_latest_tab(ctx)
    ctx.visit("new-tab.html")
    opener = ctx.session.get_page()
    with tabs_closed_after(ctx, opener, NEW_TAB_TARGET):
        ctx.session.click("#external")
        url = latest_tab_url(ctx, NEW_TAB_TARGET)
        assert NEW_TAB_TARGET in url, url


# --- dom sanitize levels ---


def sanitize_levels_each_drop_something_more(ctx: Context) -> None:
    """``session.dom`` is the only way a level other than LOW is reachable —
    the YAML ``dom`` step is always LOW."""
    ctx.visit("api-sanitize.html")
    low, medium, high, xhigh = (
        ctx.session.dom("#target", 0, level) for level in SanitizeLevel
    )

    # Not a level difference: the cleaner strips scripts and inline styles at
    # every level, LOW included.
    for level_html in (low, medium, high, xhigh):
        assert "<script" not in level_html
        assert "style=" not in level_html

    # LOW keeps every surviving attribute and svg; MEDIUM keeps only lxml's
    # safe list and kills svg, and truncates data: URIs to their media type.
    assert 'data-secret="keep-me-out"' in low
    assert "data-secret" not in medium
    assert "<svg" in low
    assert "<svg" not in medium
    assert "base64" in low
    assert 'src="data:image/gif"' in medium

    # HIGH additionally drops the URL attributes.
    assert 'href="https://example.com/detail"' in medium
    assert "href=" not in high
    assert "src=" in medium
    assert "src=" not in high

    # XHIGH keeps only the small allowlist and unwraps div/span/section —
    # except the root, which keeps its tag.
    assert 'class="card"' in high
    assert "class=" not in xhigh
    assert "<span" in high
    assert "<span" not in xhigh
    assert xhigh.startswith('<div id="target" title="Target"'), xhigh
    assert "wrapped" in xhigh


# --- load state ---


def wait_for_load_state_returns_at_the_state_it_names(ctx: Context) -> None:
    ctx.visit("form.html")
    ctx.session.wait_for_load_state("load")
    assert ctx.js("document.readyState") == "complete"


# --- behavior ---


def humanized_typing_costs_a_delay_per_key(ctx: Context) -> None:
    """The suite's session runs ``Behavior.off()``; this is the only row that
    swaps in ``Behavior.human()``, so it must put both attributes back."""
    ctx.visit("form.html")
    instant = ctx.elapsed(lambda: ctx.session.type("#name", TYPED_TEXT))
    assert ctx.value("#name") == TYPED_TEXT
    ctx.session.fill("#name", "")

    human = Behavior.human()
    was_behavior, was_runtime = ctx.session.behavior, ctx.session.behavior_runtime
    try:
        ctx.session.behavior = human
        ctx.session.behavior_runtime = human.runtime()
        humanized = ctx.elapsed(lambda: ctx.session.type("#name", TYPED_TEXT))
    finally:
        ctx.session.behavior = was_behavior
        ctx.session.behavior_runtime = was_runtime

    assert ctx.value("#name") == TYPED_TEXT
    # The floor is per-key only: ``paced``'s post-action pause is at most
    # 800ms, so a driver typing in one shot cannot reach it.
    floor = len(TYPED_TEXT) * human.type_char_delay.min_ms / 1000
    assert humanized - instant >= floor, (
        f"humanized {humanized:.3f}s vs off {instant:.3f}s, floor {floor:.3f}s"
    )


# --- attach ---


def attach_or_skip(ctx: Context) -> None:
    """Settled before anything is spawned: a driver without ``attach`` must not
    have to leave a detached Chromium behind to find that out."""
    driver = resolve_driver(configured(ctx.driver))
    if type(driver).attach is not Driver.attach:
        return
    try:
        driver.attach("")
    except NotImplementedError as exc:
        raise ctx.skip(str(exc)) from exc


def attach_session(ctx: Context, state_dir: Path, chrome: str) -> BrowserSession:
    return BrowserSession(
        session_id="attach",
        state_dir=state_dir,
        driver=configured(ctx.driver),
        executable_path=chrome,
    )


def one_thread(name: str) -> futures.ThreadPoolExecutor:
    """A thread that owns exactly one browser session.

    A Playwright sync instance belongs to the thread that started it, and that
    thread may hold only one — the suite's own session is already holding the
    main thread's. So each session here gets a thread, and every call on it is
    submitted to that thread.
    """
    return futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix=name)


def on[T](pool: futures.Executor, work: Callable[[], T]) -> T:
    return pool.submit(work).result()


def kill_stray_chromium(profile: Path) -> None:
    """``launch_detached`` spawns Chromium before it attaches, so a failure in
    the attach half leaves a browser no ``SessionInfo`` points at and
    ``stop_detached`` cannot reach. The profile path is unique to this run."""
    pkill = shutil.which("pkill")
    if pkill is not None:
        subprocess.run([pkill, "-f", f"user-data-dir={profile}"], check=False)


def a_detached_chromium_is_driven_over_cdp(ctx: Context) -> None:
    attach_or_skip(ctx)
    chrome = chrome_binary()
    if chrome is None:
        raise ctx.skip("no Chrome/Chromium on PATH to launch a detached browser")
    with tempfile.TemporaryDirectory(
        prefix="llm-browser-attach-", ignore_cleanup_errors=True
    ) as root:
        attach_round_trip(ctx, Path(root), chrome)


def attach_round_trip(ctx: Context, root: Path, chrome: str) -> None:
    host = attach_session(ctx, root / "host", chrome)
    with one_thread("attach-host") as pool:
        try:
            detached = on(pool, lambda: host.launch_detached(headed=False))
            assert detached.status == "open"
            assert detached.cdp_url, detached
            assert detached.target_id, detached
            drive_over_cdp(ctx, root, chrome, detached.cdp_url, detached.target_id)
        finally:
            stopped = on(pool, host.stop_detached)
            kill_stray_chromium(host.session_dir / "user-data")
    assert stopped.status == "closed"
    assert host.status().status == "closed"
    a_session_launches_and_closes_its_own_browser(ctx, root, chrome)


def drive_over_cdp(
    ctx: Context, root: Path, chrome: str, cdp_url: str, target_id: str
) -> None:
    client = attach_session(ctx, root / "client", chrome)
    with one_thread("attach-client") as pool:
        try:
            attached = on(pool, lambda: client.attach(cdp_url))
            assert attached.status == "open"
            assert attached.cdp_url == cdp_url
            assert on(pool, client.status).status == "open"

            on(pool, lambda: client.goto(ctx.url("form.html")))
            on(pool, lambda: client.click("#reveal"))
            assert on(pool, lambda: revealed(client)) == "block"

            reaches_the_hosts_tab_by_its_id(ctx, root, chrome, cdp_url, target_id)
            reconnects_from_the_persisted_endpoint(ctx, root, chrome)
        finally:
            on(pool, client.close)


def revealed(session: BrowserSession) -> Any:
    return session.evaluate(
        session.get_page(), "document.querySelector('#second-form').style.display"
    )


def reaches_the_hosts_tab_by_its_id(
    ctx: Context, root: Path, chrome: str, cdp_url: str, target_id: str
) -> None:
    """``(cdp_url, target_id)`` is the whole address of a tab — enough to reach
    the one the host opened from a session that launched nothing."""
    by_tab = attach_session(ctx, root / "by-tab", chrome)
    with one_thread("attach-by-tab") as pool:
        try:
            reached = on(pool, lambda: by_tab.attach_to_tab(cdp_url, target_id))
            assert reached.status == "open"
            assert reached.target_id == target_id
        finally:
            on(pool, by_tab.close)


def reconnects_from_the_persisted_endpoint(
    ctx: Context, root: Path, chrome: str
) -> None:
    """A fresh session over the client's state dir holds no page at all, which
    is what a second CLI invocation looks like."""
    reconnected = attach_session(ctx, root / "client", chrome)
    with one_thread("attach-reconnect") as pool:
        page = on(pool, reconnected.connect)
        assert "form.html" in on(pool, lambda: reconnected.driver.page_url(page))
        assert on(pool, reconnected.status).status == "open"
        assert on(pool, reconnected.close).status == "closed"
        assert on(pool, reconnected.status).status == "closed"


def a_session_launches_and_closes_its_own_browser(
    ctx: Context, root: Path, chrome: str
) -> None:
    """The harness launches the shared session before any scenario runs, so
    ``launch``/``close`` have nowhere else to be claimed."""
    session = attach_session(ctx, root / "launched", chrome)
    with one_thread("attach-launched") as pool:
        try:
            assert on(pool, lambda: session.launch(headed=False)).status == "open"
            assert on(pool, session.status).status == "open"
            on(pool, lambda: session.goto(ctx.url("form.html")))
            here = on(pool, lambda: session.driver.page_url(session.get_page()))
            assert "form.html" in here, here
        finally:
            closed = on(pool, session.close)
    assert closed.status == "closed"
    assert session.status().status == "closed"


SCENARIOS = [
    Scenario(
        "probe sees a password",
        Section.API,
        probe_sees_the_password_field_and_the_page_text,
        covers=frozenset({"session:probe", "api:human_needed.password"}),
    ),
    Scenario(
        "probe sees a challenge",
        Section.API,
        probe_sees_a_visible_bot_challenge,
        covers=frozenset({"api:human_needed.challenge"}),
    ),
    Scenario(
        "screenshot bytes",
        Section.API,
        screenshot_bytes_returns_a_png_and_writes_nothing,
        covers=frozenset({"session:screenshot_bytes"}),
    ),
    Scenario(
        "element exists",
        Section.API,
        element_exists_answers_false_inside_its_timeout,
        covers=frozenset({"session:element_exists"}),
    ),
    Scenario(
        "find all",
        Section.API,
        find_all_returns_what_find_refuses,
        covers=frozenset({"session:find_all"}),
    ),
    Scenario(
        "explore a button",
        Section.API,
        explore_says_which_button_a_click_would_miss,
        covers=frozenset(
            {
                "session:explore",
                "session:first_match",
                "session:verified_candidates",
                "session:count_of",
            }
        ),
    ),
    Scenario(
        "explore a click cost",
        Section.API,
        explore_reads_what_a_loose_click_would_cost,
        covers=frozenset({"session:explore"}),
    ),
    Scenario(
        "explore a list",
        Section.API,
        explore_counts_the_whole_list_and_reads_only_the_sample,
        covers=frozenset({"session:explore"}),
    ),
    Scenario(
        "explore many",
        Section.API,
        explore_many_answers_every_target_in_one_page_call,
        covers=frozenset({"session:explore_many", "session:evaluate_document"}),
    ),
    Scenario(
        "survey a page",
        Section.API,
        survey_reads_what_the_page_is_made_of,
        covers=frozenset({"session:survey"}),
    ),
    Scenario(
        "latest tab",
        Section.API,
        latest_tab_reaches_the_tab_the_page_opened,
        covers=frozenset({"session:latest_tab"}),
    ),
    Scenario(
        "sanitize levels",
        Section.API,
        sanitize_levels_each_drop_something_more,
        covers=frozenset(
            {
                "session:dom",
                "api:sanitize.low",
                "api:sanitize.medium",
                "api:sanitize.high",
                "api:sanitize.xhigh",
            }
        ),
    ),
    Scenario(
        "wait for load state",
        Section.API,
        wait_for_load_state_returns_at_the_state_it_names,
        covers=frozenset({"session:wait_for_load_state"}),
    ),
    Scenario(
        "behavior human paces input",
        Section.API,
        humanized_typing_costs_a_delay_per_key,
        covers=frozenset({"api:behavior.human", "api:behavior.off"}),
        known_gaps={
            "camoufox": "the plain locator.type() path already spends ~70ms a "
            "key on Camoufox's patched Firefox, inside Behavior.human()'s own "
            "30-90ms jitter band, so the humanized path is not measurably slower",
            "nodriver": "NodriverDriver leaves humanized_type defaulted because "
            "its native CDP input already types like a person, so "
            "Behavior.human() adds paced()'s post-action pause and no per-key "
            "delay",
        },
    ),
    Scenario(
        "attach over cdp",
        Section.API,
        a_detached_chromium_is_driven_over_cdp,
        covers=frozenset(
            {
                "session:attach",
                "session:attach_to_tab",
                "session:close",
                "session:connect",
                "session:launch",
                "session:launch_detached",
                "session:status",
                "session:stop_detached",
            }
        ),
    ),
]
