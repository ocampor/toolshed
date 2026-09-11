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
from llm_browser.html import SanitizeLevel
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
