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
    # Drives the installed console script, not the library.
    CLI = "cli"


class ScenarioSkipped(Exception):
    """Not a failure: a driver may omit ``enter_frame``, and only the check knows what it needed."""


@dataclass(frozen=True)
class Timing:
    """``total`` starts before the trigger (lower bound); ``after_trigger`` after it (upper bound)."""

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
    session: BrowserSession
    site_url: str
    driver: str
    delay_ms: int = DEFAULT_DELAY_MS

    def url(self, page: str) -> str:
        separator = "&" if "?" in page else "?"
        return f"{self.site_url}/{page}{separator}delay={self.delay_ms}"

    def visit(self, page: str) -> None:
        self.session.goto(self.url(page))

    def flow(self, name: str) -> Flow:
        return load_flow_text(self.flow_file(name).read_text())

    def flow_file(self, name: str) -> Path:
        return FLOWS_DIR / f"{name}.yaml"

    def wait_now(self, selector: str, state: str, **overrides: int) -> None:
        options: dict[str, Any] = {
            "state": state,
            "timeout": TIMEOUT_MS,
            "interval": POLL_MS,
            **overrides,
        }
        self.session.wait_for_element(selector, **options)

    def wait(self, selector: str, state: str, **overrides: int) -> Callable[[], None]:
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

    def js(self, expression: str) -> Any:
        """A page-level JS expression both driver families accept, unlike the element-scoped ``evaluate``."""
        return self.session.evaluate(self.session.get_page(), expression)

    def text(self, selector: str) -> str | None:
        content = self.js(f"document.querySelector({selector!r}).textContent")
        return None if content is None else str(content)

    def value(self, selector: str) -> str:
        return str(self.js(f"document.querySelector({selector!r}).value"))

    def trusted(self, selector: str, attribute: str = "data-trusted") -> str | None:
        """``data-trusted`` is the last click or keydown; ``data-trusted-input`` the last ``input`` event."""
        seen = self.js(
            f"document.querySelector({selector!r}).getAttribute({attribute!r})"
        )
        return None if seen is None else str(seen)

    def skip(self, reason: str) -> ScenarioSkipped:
        return ScenarioSkipped(f"{self.driver}: {reason}")


Check = Callable[[Context], str | None]


@dataclass(frozen=True)
class Scenario:
    """``check`` may return a note recording which behaviour a driver has; no ``page`` field, as the check navigates."""

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
