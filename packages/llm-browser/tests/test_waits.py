"""BrowserSession.wait_for_element: the Python-side explicit wait.

Time is faked throughout — a real poll loop would make these tests sleep.
"""

import itertools
import random
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest

from llm_browser import waits
from llm_browser.constants import (
    DEFAULT_POLL_INTERVAL_MS,
    DEFAULT_WAIT_TIMEOUT_MS,
    POLL_JITTER_RATIO,
)
from llm_browser.drivers.base import Driver
from llm_browser.selectors import (
    CssSelector,
    FallbackSelector,
    IdSelector,
    XpathSelector,
)
from llm_browser.session import BrowserSession


class FakeClock:
    """A monotonic clock that only moves when the code under test sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeClock]:
    fake = FakeClock()
    shim = SimpleNamespace(monotonic=fake.monotonic, sleep=fake.sleep)
    # Swap the modules' ``time`` reference, not attributes on ``time`` itself,
    # so pytest's own timing is untouched.
    monkeypatch.setattr(waits, "time", shim)
    # ``jittered_sleep`` lives in behavior and is what the poll loop calls.
    monkeypatch.setattr("llm_browser.behavior.time", shim)
    yield fake


def make_session(tmp_path: Path, driver: MagicMock) -> BrowserSession:
    session = BrowserSession(state_dir=tmp_path, stateless=True)
    session.driver = driver
    session._page = MagicMock()
    return session


def driver_with(
    counts: list[int] | None = None,
    visible: list[bool] | None = None,
    texts: list[str | None] | None = None,
):
    """A driver whose reads walk ``counts`` / ``visible`` / ``texts``,
    repeating the last."""
    driver = MagicMock(spec=Driver)
    driver.resolve.side_effect = lambda page, selector: MagicMock(name=selector)
    driver.first.side_effect = lambda locator: locator
    driver.count.side_effect = _series(counts if counts is not None else [0])
    driver.is_visible.side_effect = _series(visible if visible is not None else [False])
    driver.text_content.side_effect = _series(texts if texts is not None else [None])
    return driver


def _series(values: list[Any]):
    remaining = list(values)

    def take(*_: Any) -> Any:
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return take


def test_returns_on_the_tick_the_element_appears(
    tmp_path: Path, clock: FakeClock
) -> None:
    driver = driver_with(counts=[0, 0, 1])
    session = make_session(tmp_path, driver)

    session.wait_for_element("#late")

    assert driver.count.call_count == 3
    assert len(clock.sleeps) == 2


def test_no_sleep_when_already_in_state(tmp_path: Path, clock: FakeClock) -> None:
    session = make_session(tmp_path, driver_with(counts=[1]))

    session.wait_for_element("#here")

    assert clock.sleeps == []


def test_timeout_message_names_selector_state_and_timeout(
    tmp_path: Path, clock: FakeClock
) -> None:
    session = make_session(tmp_path, driver_with(counts=[0]))

    with pytest.raises(TimeoutError) as excinfo:
        session.wait_for_element("#missing", state="visible", timeout=1_000)

    assert str(excinfo.value) == "#missing did not become visible within 1000ms"


def test_timeout_fires_at_the_deadline_not_a_tick_past_it(
    tmp_path: Path, clock: FakeClock
) -> None:
    session = make_session(tmp_path, driver_with(counts=[0]))

    with pytest.raises(TimeoutError):
        session.wait_for_element("#missing", timeout=2_000, interval=500)

    assert clock.now - 1000.0 == pytest.approx(2.0)


def test_the_last_sleep_is_clamped_to_what_is_left(
    tmp_path: Path, clock: FakeClock
) -> None:
    """An interval far wider than the budget must not stretch the wait."""
    session = make_session(tmp_path, driver_with(counts=[0]))

    with pytest.raises(TimeoutError):
        session.wait_for_element("#missing", timeout=1_000, interval=10_000)

    assert clock.sleeps == [pytest.approx(1.0)]


def test_zero_timeout_checks_exactly_once(tmp_path: Path, clock: FakeClock) -> None:
    driver = driver_with(counts=[0])
    session = make_session(tmp_path, driver)

    with pytest.raises(TimeoutError):
        session.wait_for_element("#missing", timeout=0)

    assert driver.count.call_count == 1
    assert clock.sleeps == []


def test_zero_timeout_still_returns_when_already_in_state(
    tmp_path: Path, clock: FakeClock
) -> None:
    session = make_session(tmp_path, driver_with(counts=[1]))

    session.wait_for_element("#here", timeout=0)

    assert clock.sleeps == []


def test_a_driver_error_escapes_instead_of_reading_as_not_yet(
    tmp_path: Path, clock: FakeClock
) -> None:
    """A CDP failure is not "the element is missing" — it must not become a
    timeout, and a later "make polling robust" edit must not swallow it."""
    driver = driver_with(counts=[0])
    driver.count.side_effect = RuntimeError("Could not find node with given id")
    session = make_session(tmp_path, driver)

    with pytest.raises(RuntimeError, match="Could not find node"):
        session.wait_for_element("#boom")


def test_a_navigation_during_a_detached_wait_reads_as_not_yet(
    tmp_path: Path, clock: FakeClock
) -> None:
    """The navigation that destroys the context is what `detached` is waiting
    for, so the poll re-asks on the next tick instead of unwinding."""
    driver = driver_with(counts=[1])
    driver.count.side_effect = [
        RuntimeError(
            "Execution context was destroyed, most likely because of a navigation."
        ),
        0,
    ]
    session = make_session(tmp_path, driver)

    session.wait_for_element("#gone", state="detached")

    assert driver.count.call_count == 2


def test_a_detached_wait_still_re_raises_any_other_driver_error(
    tmp_path: Path, clock: FakeClock
) -> None:
    """Only the navigation message is forgiven; a CDP failure is still a bug
    to surface, not "the element is still there"."""
    driver = driver_with(counts=[1])
    driver.count.side_effect = RuntimeError("Could not find node with given id")
    session = make_session(tmp_path, driver)

    with pytest.raises(RuntimeError, match="Could not find node"):
        session.wait_for_element("#boom", state="detached")


def test_a_visibility_error_escapes_too(tmp_path: Path, clock: FakeClock) -> None:
    driver = driver_with(visible=[False])
    driver.is_visible.side_effect = RuntimeError("Execution context was destroyed")
    session = make_session(tmp_path, driver)

    with pytest.raises(RuntimeError, match="Execution context"):
        session.wait_for_element("#boom", state="visible")


@pytest.mark.parametrize(
    "selector,rendered",
    [
        ("#plain", "#plain"),
        (CssSelector(css=".a"), ".a"),
        (XpathSelector(xpath="//div"), "xpath=//div"),
        (IdSelector(id="main"), '[id="main"]'),
        (
            FallbackSelector(
                primary=CssSelector(css="#a"), fallback=IdSelector(id="b")
            ),
            '#a or [id="b"]',
        ),
    ],
)
def test_the_message_renders_the_selector_the_way_it_was_written(
    tmp_path: Path, clock: FakeClock, selector: Any, rendered: str
) -> None:
    """A pydantic repr in a user-facing message would not match the docs."""
    session = make_session(tmp_path, driver_with(counts=[0]))

    with pytest.raises(TimeoutError) as excinfo:
        session.wait_for_element(selector, timeout=0)

    assert str(excinfo.value) == f"{rendered} did not become attached within 0ms"


@pytest.mark.parametrize(
    "state,counts,visible",
    [
        ("attached", [0, 1], None),
        ("detached", [1, 0], None),
        ("visible", None, [False, True]),
        ("hidden", None, [True, False]),
    ],
)
def test_every_state_polls_until_satisfied(
    tmp_path: Path,
    clock: FakeClock,
    state: Any,
    counts: list[int] | None,
    visible: list[bool] | None,
) -> None:
    driver = driver_with(counts=counts, visible=visible)
    session = make_session(tmp_path, driver)

    session.wait_for_element("#el", state=state)

    assert len(clock.sleeps) == 1


@pytest.mark.parametrize("state", ["attached", "detached"])
def test_presence_states_never_read_visibility(
    tmp_path: Path, clock: FakeClock, state: Any
) -> None:
    """No ``is_visible`` means no in-page script on the nodriver path."""
    driver = driver_with(counts=[1, 0])
    session = make_session(tmp_path, driver)

    session.wait_for_element("#el", state=state)

    driver.is_visible.assert_not_called()


def test_locator_is_re_resolved_every_tick(tmp_path: Path, clock: FakeClock) -> None:
    driver = driver_with(counts=[0, 0, 1])
    session = make_session(tmp_path, driver)

    session.wait_for_element("#late")

    assert driver.resolve.call_count == 3


def test_typed_selectors_are_resolved(tmp_path: Path, clock: FakeClock) -> None:
    driver = driver_with(counts=[1])
    session = make_session(tmp_path, driver)

    session.wait_for_element(CssSelector(css="#a"))

    assert driver.resolve.call_args.args[1] == "#a"


def test_sleeps_stay_within_the_jitter_ratio(tmp_path: Path, clock: FakeClock) -> None:
    driver = driver_with(counts=[0] * 40 + [1])
    session = make_session(tmp_path, driver)

    session.wait_for_element("#late", timeout=10_000_000, interval=400)

    low, high = 0.4 * (1 - POLL_JITTER_RATIO), 0.4 * (1 + POLL_JITTER_RATIO)
    assert len(clock.sleeps) == 40
    assert all(low <= s <= high for s in clock.sleeps)


def test_sleeps_are_not_a_fixed_cadence(tmp_path: Path, clock: FakeClock) -> None:
    driver = driver_with(counts=[0] * 20 + [1])
    session = make_session(tmp_path, driver)

    session.wait_for_element("#late", timeout=10_000_000)

    assert len(set(clock.sleeps)) > 1


def test_poll_jitter_window_brackets_the_interval() -> None:
    """Guards the jitter window's arithmetic, independent of the loop."""
    jitter = waits.poll_jitter(DEFAULT_POLL_INTERVAL_MS)
    assert jitter.min_ms == 350
    assert jitter.max_ms == 650


def test_poll_for_state_is_driver_agnostic() -> None:
    """No session, no page: the loop only needs a Driver and a page object."""
    driver = driver_with(counts=[1])

    waits.poll_for_state(
        driver,
        page=MagicMock(),
        selector="#a",
        state="attached",
        timeout_ms=DEFAULT_WAIT_TIMEOUT_MS,
        interval_ms=DEFAULT_POLL_INTERVAL_MS,
        rng=random.Random(0),
    )

    assert driver.count.call_count == 1


# --- the stable state ---


def test_stable_returns_once_the_text_holds_still(
    tmp_path: Path, clock: FakeClock
) -> None:
    session = make_session(tmp_path, driver_with(texts=["done"]))

    session.wait_for_element("#reply", state="stable", settle=1000, timeout=10_000)

    # First read starts the clock, and the text has to hold for a full settle.
    assert clock.now - 1000.0 >= 1.0


def test_stable_times_out_while_the_text_keeps_changing(
    tmp_path: Path, clock: FakeClock
) -> None:
    driver = driver_with()
    chunks = iter(str(n) for n in itertools.count())
    driver.text_content.side_effect = lambda locator: next(chunks)
    session = make_session(tmp_path, driver)

    with pytest.raises(TimeoutError, match="#reply did not become stable within"):
        session.wait_for_element("#reply", state="stable", settle=100, timeout=1000)


def test_stable_never_settles_on_an_element_that_is_not_there(
    tmp_path: Path, clock: FakeClock
) -> None:
    """``None`` is "nothing to read yet", not "settled on nothing"."""
    session = make_session(tmp_path, driver_with(texts=[None]))

    with pytest.raises(TimeoutError):
        session.wait_for_element("#reply", state="stable", settle=1, timeout=500)


def test_stable_restarts_the_clock_on_every_change(
    tmp_path: Path, clock: FakeClock
) -> None:
    driver = driver_with(texts=["a", "b", "b", "b", "b", "b"])
    session = make_session(tmp_path, driver)

    session.wait_for_element("#reply", state="stable", settle=600, timeout=10_000)

    # "a" then "b": settling could not have started before the second read.
    assert driver.text_content.call_count >= 3


def test_a_settle_that_does_not_fit_the_budget_fails_before_polling(
    tmp_path: Path, clock: FakeClock
) -> None:
    """The wait could only ever time out, so say why instead of pretending."""
    session = make_session(tmp_path, driver_with(texts=["done"]))

    with pytest.raises(ValueError, match="must be less than timeout"):
        session.wait_for_element("#reply", state="stable", settle=2000, timeout=500)

    assert clock.sleeps == []


def test_find_rejects_an_ambiguous_selector_before_polling(
    tmp_path: Path, clock: FakeClock
) -> None:
    """Two matches is a mistake, not a state to wait for: no budget is burned."""
    session = make_session(tmp_path, driver_with(counts=[2], visible=[False]))

    with pytest.raises(ValueError, match="Expected 1 element"):
        session.find("#dup", timeout=10_000)

    assert clock.sleeps == []
