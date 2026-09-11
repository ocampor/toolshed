"""What one conformance check is, and the handle it is given to run.

A ``Scenario`` is data: a name, the fixture page it drives, the callable that
exercises the library, and the drivers it is known to fail on today. Both
front ends — ``llm-browser-check`` and the pytest wrapper — walk the same
list, so a scenario is written once and reported twice.
"""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from llm_browser.flows import load_flow_text
from llm_browser.models import Flow
from llm_browser.session import BrowserSession

FLOWS_DIR = Path(__file__).parent / "flows"

# Short enough to keep a full run quick, long enough that a driver which
# ignores the wait and answers immediately fails the lower time bound.
DEFAULT_DELAY_MS = 1_000

POLL_MS = 200
SETTLE_MS = 800
TIMEOUT_MS = 8_000

# Real browsers on a loaded machine are not metronomes.
SLACK_MS = 500


class Outcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    XFAIL = "xfail"
    XPASS = "xpass"
    SKIP = "skip"

    @property
    def is_failure(self) -> bool:
        """``xpass`` counts: a gap that closed leaves the table lying."""
        return self in (Outcome.FAIL, Outcome.XPASS)


class Section(StrEnum):
    # Not a scenario group: the row a driver's own launch or teardown gets.
    SESSION = "session"
    WAITS = "waits"
    FLOWS = "flows"
    INPUTS = "inputs"
    FRAMES = "frames"
    STEALTH = "stealth"
    STEPS = "steps"
    OPTIONS = "options"
    RESULTS = "results"
    API = "api"


class ScenarioSkipped(Exception):
    """This driver has no API for what the scenario exercises.

    Not a failure: a driver is allowed to not implement ``enter_frame``. It is
    raised by the check itself, because only the check knows what it needed.
    """


@dataclass(frozen=True)
class Timing:
    """Two honest clocks around one wait.

    ``total`` starts before the trigger (a navigation or a click), so the
    page's ``setTimeout`` cannot have started any earlier — it is the lower
    bound. ``after_trigger`` starts once the trigger returned, by which point
    the timer is already running — it is the upper bound, and charging it with
    the trigger's own cost would only make the ceiling meaningless.
    """

    total: float
    after_trigger: float

    def assert_within(self, delay_ms: int, extra_ms: int = 0) -> None:
        floor = (delay_ms + extra_ms) / 1000
        ceiling = (delay_ms + extra_ms + 2 * POLL_MS + SLACK_MS) / 1000
        assert self.total >= floor, f"returned after {self.total:.3f}s, before {floor}s"
        assert self.after_trigger <= ceiling, (
            f"took {self.after_trigger:.3f}s, budget {ceiling}s"
        )


@dataclass(frozen=True)
class Context:
    """Everything a check is allowed to touch: one live session and the site.

    The helpers exist so a check reads as the story it is telling rather than
    as timeout bookkeeping.
    """

    session: BrowserSession
    site_url: str
    driver: str
    delay_ms: int = DEFAULT_DELAY_MS

    # --- The site ---

    def url(self, page: str) -> str:
        separator = "&" if "?" in page else "?"
        return f"{self.site_url}/{page}{separator}delay={self.delay_ms}"

    def visit(self, page: str) -> None:
        self.session.goto(self.url(page))

    def flow(self, name: str) -> Flow:
        return load_flow_text((FLOWS_DIR / f"{name}.yaml").read_text())

    # --- Waiting ---

    def wait_now(self, selector: str, state: str, **overrides: int) -> None:
        options: dict[str, Any] = {
            "state": state,
            "timeout": TIMEOUT_MS,
            "interval": POLL_MS,
            **overrides,
        }
        self.session.wait_for_element(selector, **options)

    def wait(self, selector: str, state: str, **overrides: int) -> Callable[[], None]:
        """The same wait, deferred, so ``timed`` can bracket it."""
        return lambda: self.wait_now(selector, state, **overrides)

    def timed(self, trigger: Callable[[], Any], wait: Callable[[], Any]) -> Timing:
        start = time.monotonic()
        trigger()
        triggered = time.monotonic()
        wait()
        end = time.monotonic()
        return Timing(total=end - start, after_trigger=end - triggered)

    def elapsed(self, action: Callable[[], Any]) -> float:
        start = time.monotonic()
        action()
        return time.monotonic() - start

    # --- Reading ---

    def js(self, expression: str) -> Any:
        """Read the page from the page's own side.

        Both driver families take a plain JS *expression* here, which the
        element-scoped ``evaluate`` cannot claim (Playwright wants an arrow
        function, nodriver a function body), so page-level reads keep an
        assertion driver-neutral.
        """
        return self.session.evaluate(self.session.get_page(), expression)

    def text(self, selector: str) -> str | None:
        content = self.js(f"document.querySelector({selector!r}).textContent")
        return None if content is None else str(content)

    def value(self, selector: str) -> str:
        return str(self.js(f"document.querySelector({selector!r}).value"))

    def trusted(self, selector: str, attribute: str = "data-trusted") -> str | None:
        """What the page's recorder saw for the last event on ``selector``.

        ``data-trusted`` is the last click or keydown; ``data-trusted-input``
        the last ``input`` event — drivers differ on which they emit, and the
        difference is worth naming rather than averaging away.
        """
        seen = self.js(
            f"document.querySelector({selector!r}).getAttribute({attribute!r})"
        )
        return None if seen is None else str(seen)

    def skip(self, reason: str) -> ScenarioSkipped:
        return ScenarioSkipped(f"{self.driver}: {reason}")


Check = Callable[[Context], str | None]


@dataclass(frozen=True)
class Scenario:
    """One conformance check, plus the drivers it is known to fail on today.

    ``check`` may return a one-line note — used where drivers legitimately
    differ and the point is to *record* which behaviour this one has rather
    than to force a single answer.

    ``covers`` names the public surface this scenario exercises — step types,
    step fields, step options, session methods (see
    :mod:`llm_browser_conformance.coverage` for the key grammar). It is what
    ``docs/coverage.md`` is built from, and what lets a test fail when the
    library grows a step type or a field nothing checks.

    There is deliberately no ``page`` field: the check navigates, so a second
    copy of the page name here would be documentation nothing verifies.
    """

    name: str
    section: Section
    check: Check
    drivers: frozenset[str] | None = None
    known_gaps: Mapping[str, str] = field(default_factory=dict)
    covers: frozenset[str] = frozenset()

    def applies_to(self, driver: str) -> bool:
        return self.drivers is None or driver in self.drivers

    def gap_for(self, driver: str) -> str | None:
        return self.known_gaps.get(driver)


def raises(expected: type[BaseException], action: Callable[[], Any]) -> BaseException:
    """``pytest.raises`` for checks that also run outside pytest."""
    try:
        action()
    except expected as exc:
        return exc
    raise AssertionError(f"expected {expected.__name__}, nothing was raised")
