import itertools
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
    READ_TIMEOUT_MS,
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
    driver = MagicMock(spec=Driver)
    driver.resolve.side_effect = lambda page, selector: MagicMock(name=selector)
    driver.first.side_effect = lambda locator: locator
    driver.count.side_effect = _series(counts if counts is not None else [0])
    driver.is_visible.side_effect = _series(visible if visible is not None else [False])
    driver.text_content.side_effect = _series(texts if texts is not None else [None])
    return driver


def driver_with_attributes(attributes: list[dict[str, str | None]]):
    driver = driver_with(counts=[1])
    take = _series(attributes)
    driver.is_enabled.side_effect = lambda locator: Driver.is_enabled(driver, locator)
    driver.get_attribute.side_effect = lambda locator, name: take().get(name)
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
    driver = driver_with(counts=[0])
    driver.count.side_effect = RuntimeError("Could not find node with given id")
    session = make_session(tmp_path, driver)

    with pytest.raises(RuntimeError, match="Could not find node"):
        session.wait_for_element("#boom")


def test_a_navigation_during_a_detached_wait_reads_as_not_yet(
    tmp_path: Path, clock: FakeClock
) -> None:
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
    jitter = waits.poll_jitter(DEFAULT_POLL_INTERVAL_MS)
    assert jitter.min_ms == 350
    assert jitter.max_ms == 650


def test_poll_for_state_is_driver_agnostic() -> None:
    driver = driver_with(counts=[1])

    waits.poll_for_state(
        driver,
        page=MagicMock(),
        selector="#a",
        state="attached",
        timeout_ms=DEFAULT_WAIT_TIMEOUT_MS,
        interval_ms=DEFAULT_POLL_INTERVAL_MS,
    )

    assert driver.count.call_count == 1


def test_stable_returns_once_the_text_holds_still(
    tmp_path: Path, clock: FakeClock
) -> None:
    session = make_session(tmp_path, driver_with(texts=["done"]))

    session.wait_for_element("#reply", state="stable", settle=1000, timeout=10_000)

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
    session = make_session(tmp_path, driver_with(texts=[None]))

    with pytest.raises(TimeoutError):
        session.wait_for_element("#reply", state="stable", settle=1, timeout=500)


def test_stable_restarts_the_clock_on_every_change(
    tmp_path: Path, clock: FakeClock
) -> None:
    driver = driver_with(texts=["a", "b", "b", "b", "b", "b"])
    session = make_session(tmp_path, driver)

    session.wait_for_element("#reply", state="stable", settle=600, timeout=10_000)

    assert driver.text_content.call_count >= 3


def test_a_settle_that_does_not_fit_the_budget_fails_before_polling(
    tmp_path: Path, clock: FakeClock
) -> None:
    session = make_session(tmp_path, driver_with(texts=["done"]))

    with pytest.raises(ValueError, match="must be less than timeout"):
        session.wait_for_element("#reply", state="stable", settle=2000, timeout=500)

    assert clock.sleeps == []


def test_find_rejects_an_ambiguous_selector_before_polling(
    tmp_path: Path, clock: FakeClock
) -> None:
    session = make_session(tmp_path, driver_with(counts=[2], visible=[False]))

    with pytest.raises(ValueError, match="expected 1 element for '#dup', found 2"):
        session.find("#dup", timeout=10_000)

    assert clock.sleeps == []


ENABLED: dict[str, str | None] = {}
NATIVE_DISABLED: dict[str, str | None] = {"disabled": ""}
ARIA_DISABLED: dict[str, str | None] = {"aria-disabled": "true"}


@pytest.mark.parametrize(
    "attributes, state",
    [
        (ENABLED, "enabled"),
        (NATIVE_DISABLED, "disabled"),
        (ARIA_DISABLED, "disabled"),
        ({"aria-disabled": "false"}, "enabled"),
    ],
)
def test_enabled_reads_both_spellings_of_disabled(
    tmp_path: Path,
    clock: FakeClock,
    attributes: dict[str, str | None],
    state: str,
) -> None:
    session = make_session(tmp_path, driver_with_attributes([attributes]))

    session.wait_for_element("#submit", state=state)

    assert clock.sleeps == []


def test_enabled_waits_for_the_attribute_to_go(
    tmp_path: Path, clock: FakeClock
) -> None:
    driver = driver_with_attributes([NATIVE_DISABLED, NATIVE_DISABLED, ENABLED])
    session = make_session(tmp_path, driver)

    session.wait_for_element("#submit", state="enabled")

    assert len(clock.sleeps) == 2


def test_enabled_times_out_while_the_control_stays_locked(
    tmp_path: Path, clock: FakeClock
) -> None:
    session = make_session(tmp_path, driver_with_attributes([NATIVE_DISABLED]))

    with pytest.raises(TimeoutError, match="did not become enabled"):
        session.wait_for_element("#submit", state="enabled", timeout=1000)


def test_an_element_that_is_not_there_is_neither_enabled_nor_disabled(
    tmp_path: Path, clock: FakeClock
) -> None:
    driver = driver_with(counts=[0])
    driver.is_enabled.side_effect = AssertionError("read a missing element")

    session = make_session(tmp_path, driver)

    for state in ("enabled", "disabled"):
        with pytest.raises(TimeoutError):
            session.wait_for_element("#submit", state=state, timeout=0)


def driver_with_text(matches: list[bool]) -> MagicMock:
    driver = driver_with()
    driver.evaluate.side_effect = _series(matches)
    driver.all.side_effect = lambda locator: [locator]
    return driver


def test_wait_for_text_present(tmp_path: Path, clock: FakeClock) -> None:
    driver = driver_with_text([False, False, True])
    session = make_session(tmp_path, driver)

    session.wait_for_text("Sesión finalizada")

    assert len(clock.sleeps) == 2
    assert '"Sesi\\u00f3n finalizada"' in driver.evaluate.call_args.args[1]


def test_wait_for_text_absent(tmp_path: Path, clock: FakeClock) -> None:
    driver = driver_with_text([True, False])
    session = make_session(tmp_path, driver)

    session.wait_for_text("Cargando", state="detached")

    assert len(clock.sleeps) == 1


def test_wait_for_text_scoped(tmp_path: Path, clock: FakeClock) -> None:
    driver = driver_with_text([True])
    session = make_session(tmp_path, driver)

    session.wait_for_text("finalizada", selector=CssSelector(css=".toast"))

    assert driver.resolve.call_args.args[1] == ".toast"
    assert driver.evaluate.call_args.args[0] is not session._page


def test_a_text_timeout_names_the_text_and_the_direction(
    tmp_path: Path, clock: FakeClock
) -> None:
    session = make_session(tmp_path, driver_with_text([False]))

    with pytest.raises(TimeoutError) as excinfo:
        session.wait_for_text("Listo", selector="#panel", timeout=1_000)

    assert str(excinfo.value) == (
        "text 'Listo' inside #panel did not become present within 1000ms"
    )


def driver_error(name: str, message: str) -> Exception:
    # Each driver raises its own TimeoutError class, and the code matches on the name.
    return type(name, (Exception,), {})(message)


def test_a_scoped_text_read_is_bounded(tmp_path: Path, clock: FakeClock) -> None:
    driver = driver_with_text([True])
    session = make_session(tmp_path, driver)

    session.wait_for_text("finalizada", selector=".toast")

    assert driver.evaluate.call_args.args[2] == READ_TIMEOUT_MS


def test_a_scope_that_detaches_mid_tick_has_no_text(
    tmp_path: Path, clock: FakeClock
) -> None:
    # A watched toast can vanish between listing and read; that is "no text", not an error.
    driver = driver_with_text([True])
    driver.evaluate.side_effect = driver_error(
        "TimeoutError", "element is not attached"
    )
    session = make_session(tmp_path, driver)

    session.wait_for_text("finalizada", selector=".toast", state="detached")

    with pytest.raises(TimeoutError):
        session.wait_for_text("finalizada", selector=".toast", timeout=0)


def test_a_text_script_that_cannot_run_is_not_a_missing_scope(
    tmp_path: Path, clock: FakeClock
) -> None:
    driver = driver_with_text([True])
    driver.evaluate.side_effect = driver_error(
        "ReferenceError", "renderedText is not defined"
    )
    session = make_session(tmp_path, driver)

    with pytest.raises(Exception, match="renderedText is not defined"):
        session.wait_for_text("finalizada", selector=".toast")


def test_waiting_for_no_text_is_rejected(tmp_path: Path, clock: FakeClock) -> None:
    # Every page renders "", so the wait would always return True on the first tick.
    session = make_session(tmp_path, driver_with_text([False]))

    with pytest.raises(ValueError, match="needs text"):
        session.wait_for_text("")
    with pytest.raises(ValueError, match="needs text"):
        session.text_present("")


def test_text_present_is_one_read_with_no_waiting(
    tmp_path: Path, clock: FakeClock
) -> None:
    session = make_session(tmp_path, driver_with_text([False]))

    assert session.text_present("Listo") is False
    assert clock.sleeps == []
