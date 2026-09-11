"""The ``solve_captcha`` step: the loop around the registered reader."""

from types import SimpleNamespace
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest

from llm_browser import captcha
from llm_browser.actions import execute_action
from llm_browser.captcha import CaptchaReader, normalize_answer
from llm_browser.constants import CAPTCHA_SETTLE_MS
from llm_browser.flows import load_flow_text, run_flow
from llm_browser.models import FlowSuccess, SolveCaptchaStep
from llm_browser.results import CaptchaResult, ErrorResult

PNG = b"\x89PNG\r\n\x1a\nfake"
ANSWER = "7fkq2"


@pytest.fixture(autouse=True)
def no_reader_left_registered() -> Iterator[None]:
    """The reader is process-wide, so every test puts it back."""
    yield
    captcha.set_reader(None)


def captcha_step(**overrides: Any) -> SolveCaptchaStep:
    fields: dict[str, Any] = {
        "name": "captcha",
        "action": "solve_captcha",
        "image": "#captcha-img",
        "input": "#captcha-answer",
        "submit": "#submit",
        "error": "#captcha-error",
        # Every test drives the verdict itself; no test may sleep.
        "timeout": 0,
        **overrides,
    }
    return SolveCaptchaStep(**fields)


def replying(*replies: str) -> tuple[CaptchaReader, list[bytes]]:
    """A reader walking ``replies``, plus the crops it was shown."""
    seen: list[bytes] = []
    remaining = list(replies)

    def read(png: bytes, prompt: str | None) -> str:
        seen.append(png)
        return remaining.pop(0)

    return read, seen


class FakeClock:
    """A monotonic clock that only moves when the code under test waits."""

    def __init__(self) -> None:
        self.now = 1000.0

    def wait(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    """Fake the verdict poll's clock so a test can price its waiting.

    Both things that cost time are routed through it: the pause between ticks
    (charged at its worst case, which is what a budget claim has to survive)
    and, via ``page(clock=)``, a wait that saw nothing.
    """
    fake = FakeClock()
    monkeypatch.setattr(captcha, "time", SimpleNamespace(monotonic=lambda: fake.now))
    monkeypatch.setattr(
        captcha,
        "jittered_sleep",
        lambda jitter, rng: fake.wait(jitter.max_ms / 1000.0),
    )
    return fake


def page(
    session: MagicMock,
    step: SolveCaptchaStep,
    *,
    input_attached: list[bool],
    error_visible: list[bool] | None = None,
    clock: FakeClock | None = None,
) -> list[tuple[Any, int]]:
    """Script what the page answers, per selector, read in turn.

    Each list is consumed one read at a time and its last value then repeats,
    so a test says only as much about the page as it cares about. ``input`` is
    asked both by the verdict poll and by the settle re-check; ``error`` both
    before the answer goes in (is the banner stale?) and during the poll.

    With a ``clock``, a read that answers ``False`` charges its whole timeout:
    that is a wait that watched for something and never saw it. Returns the
    ``(selector, timeout)`` of every read, which is how a test pins the budget
    a wait was actually given.
    """
    queues = {
        step.input: list(input_attached),
        step.error: list(error_visible or [False]),
    }
    reads: list[tuple[Any, int]] = []

    def exists(selector: Any, timeout: int = 0, *, state: str = "attached") -> bool:
        queue = queues[selector]
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        reads.append((selector, timeout))
        if clock is not None and not answer:
            clock.wait(timeout / 1000.0)
        return answer

    session.element_exists.side_effect = exists
    return reads


def solved(session: MagicMock, step: SolveCaptchaStep, read: CaptchaReader) -> Any:
    captcha.set_reader(read)
    return execute_action(session, step)


@pytest.mark.parametrize(
    "reply,expected",
    [
        ("7fkq2", "7fkq2"),
        ("  7FKQ2\n", "7FKQ2"),
        ("7 f k q 2", "7fkq2"),
        ("The code is: 7fkq2.", None),
        ("UNREADABLE", None),
        ("unreadable", None),
        ("ab", None),
        ("abcdefghijklm", None),
        ("", None),
        ("...", None),
    ],
)
def test_normalize_answer(reply: str, expected: str | None) -> None:
    assert normalize_answer(reply) == expected


def test_a_right_answer_on_the_first_attempt(mock_session: MagicMock) -> None:
    step = captcha_step()
    page(mock_session, step, input_attached=[False])
    read, seen = replying(ANSWER)

    result = solved(mock_session, step, read)

    assert isinstance(result, CaptchaResult)
    assert result.attempts == 1
    assert seen == [PNG]
    mock_session.fill.assert_called_once_with("#captcha-answer", ANSWER)
    mock_session.click.assert_called_once_with("#submit")


def test_a_rejected_answer_is_retried_against_a_fresh_crop(
    mock_session: MagicMock,
) -> None:
    step = captcha_step()
    page(
        mock_session,
        step,
        # attached for the first verdict, gone for the second.
        input_attached=[True, False],
        # no banner before the first answer, one after it, still up before the
        # second — the page never clears it.
        error_visible=[False, True, True],
    )
    mock_session.screenshot_bytes.side_effect = [b"first-crop", b"second-crop"]
    read, seen = replying("wrong", ANSWER)

    result = solved(mock_session, step, read)

    assert isinstance(result, CaptchaResult)
    assert result.attempts == 2
    assert seen == [b"first-crop", b"second-crop"], "the second attempt reused a crop"


def test_running_out_of_retries_asks_for_a_human(mock_session: MagicMock) -> None:
    step = captcha_step(retries=2)
    page(mock_session, step, input_attached=[True], error_visible=[False, True])
    read, _ = replying(ANSWER, ANSWER)

    result = solved(mock_session, step, read)

    assert isinstance(result, ErrorResult)
    assert result.human_needed is True
    assert "2 attempts" in result.message


def test_an_unreadable_reply_spends_the_attempt_without_typing(
    mock_session: MagicMock,
) -> None:
    step = captcha_step(retries=1)
    read, _ = replying("UNREADABLE")

    result = solved(mock_session, step, read)

    assert isinstance(result, ErrorResult)
    assert result.human_needed is True
    mock_session.fill.assert_not_called()


def test_no_registered_reader_asks_for_a_human_without_touching_the_page(
    mock_session: MagicMock,
) -> None:
    """Nothing here can succeed, and a crop nobody will look at is wasted work
    on a site watching for it."""
    result = execute_action(mock_session, captcha_step())

    assert isinstance(result, ErrorResult)
    assert result.human_needed is True
    assert "no captcha reader is configured" in result.message
    mock_session.screenshot_bytes.assert_not_called()
    mock_session.fill.assert_not_called()
    mock_session.element_exists.assert_not_called()


def test_the_registered_reader_is_the_one_that_gets_called(
    mock_session: MagicMock,
) -> None:
    step = captcha_step()
    page(mock_session, step, input_attached=[False])
    stale, _ = replying("stale")
    fresh, seen = replying(ANSWER)
    captcha.set_reader(stale)
    captcha.set_reader(fresh)

    result = execute_action(mock_session, step)

    assert isinstance(result, CaptchaResult)
    assert seen == [PNG]


def test_a_reader_that_says_it_cannot_look_stops_after_one_crop(
    mock_session: MagicMock,
) -> None:
    """A host with a reader wired but nothing behind it right now — an HTTP run
    with no client attached — is a human handoff, not three wrong guesses."""
    step = captcha_step(retries=3)
    calls: list[bytes] = []

    def read(png: bytes, prompt: str | None) -> str:
        calls.append(png)
        raise captcha.ReaderUnavailable("no client attached to this run")

    result = solved(mock_session, step, read)

    assert isinstance(result, ErrorResult)
    assert result.human_needed is True
    assert "no captcha reader available in this run" in result.message
    assert len(calls) == 1, "spent a retry on a reader that cannot look"
    mock_session.fill.assert_not_called()
    mock_session.click.assert_not_called()


def test_a_reader_that_raises_fails_the_step_instead_of_the_run(
    mock_session: MagicMock,
) -> None:
    step = captcha_step()

    def read(png: bytes, prompt: str | None) -> str:
        raise RuntimeError("sampling API is down")

    result = solved(mock_session, step, read)

    assert isinstance(result, ErrorResult)
    assert "sampling API is down" in result.message
    assert result.human_needed is False, "an ordinary reader fault is retryable"


def test_the_answer_never_reaches_the_result(mock_session: MagicMock) -> None:
    step = captcha_step()
    page(mock_session, step, input_attached=[False])
    read, _ = replying(ANSWER)

    result = solved(mock_session, step, read)

    assert ANSWER not in str(result.model_dump())


def test_a_banner_the_page_never_cleared_is_not_this_answer_s_verdict(
    mock_session: MagicMock,
) -> None:
    """The blocking bug: a rejection left over from the previous attempt made
    the next correct answer come back as `human_needed`."""
    step = captcha_step()
    page(
        mock_session,
        step,
        input_attached=[False],
        error_visible=[True],  # already showing when the answer goes in
    )
    read, _ = replying(ANSWER)

    result = solved(mock_session, step, read)

    assert isinstance(result, CaptchaResult)
    assert result.attempts == 1


def test_a_banner_that_appears_after_the_answer_is_a_rejection(
    mock_session: MagicMock,
) -> None:
    """The single-page case: no reload, the banner simply was not there
    before and is now."""
    step = captcha_step(retries=1)
    page(mock_session, step, input_attached=[True], error_visible=[False, True])
    read, _ = replying(ANSWER)

    result = solved(mock_session, step, read)

    assert isinstance(result, ErrorResult)
    assert result.human_needed is True


def test_a_reload_that_puts_the_banner_back_up_is_a_rejection(
    mock_session: MagicMock, clock: FakeClock
) -> None:
    """A reload takes the input away and brings it back, and the banner it
    renders is a fresh verdict even though one was already showing."""
    step = captcha_step(retries=1, timeout=5_000)
    page(
        mock_session,
        step,
        # gone, back (the reload), then attached for the verdict read.
        input_attached=[False, True, True],
        error_visible=[True],  # stale before, and rendered again after
        clock=clock,
    )
    read, _ = replying(ANSWER)

    result = solved(mock_session, step, read)

    assert isinstance(result, ErrorResult)
    assert result.human_needed is True


def test_an_input_that_only_flickered_is_not_acceptance(
    mock_session: MagicMock, clock: FakeClock
) -> None:
    """Acceptance is the input staying gone, not one lucky read of it."""
    step = captcha_step(retries=1, timeout=5_000, error=None)
    page(mock_session, step, input_attached=[False, True], clock=clock)
    read, _ = replying(ANSWER)

    result = solved(mock_session, step, read)

    assert isinstance(result, ErrorResult)


def test_the_settle_never_pushes_a_verdict_past_its_budget(
    mock_session: MagicMock, clock: FakeClock
) -> None:
    """`timeout` bounds the whole verdict. A settle window wider than what is
    left of it has to shrink, not overrun."""
    step = captcha_step(retries=1, timeout=200, error=None)
    reads = page(mock_session, step, input_attached=[False], clock=clock)
    read, _ = replying(ANSWER)
    start = clock.now

    result = solved(mock_session, step, read)

    assert isinstance(result, CaptchaResult)
    assert reads[-1] == (step.input, 200), "the settle ignored the remaining budget"
    assert round((clock.now - start) * 1000) <= step.timeout


def test_a_spent_budget_takes_the_read_it_already_has(
    mock_session: MagicMock, clock: FakeClock
) -> None:
    """With nothing left to spend, "detached right now" is the answer — there
    is no budget to confirm it with."""
    step = captcha_step(retries=1, timeout=0, error=None)
    reads = page(mock_session, step, input_attached=[False], clock=clock)
    read, _ = replying(ANSWER)
    start = clock.now

    result = solved(mock_session, step, read)

    assert isinstance(result, CaptchaResult)
    assert reads == [(step.input, 0)], "waited anyway with no budget left"
    assert clock.now == start


def test_a_roomy_budget_still_confirms_the_input_stayed_gone(
    mock_session: MagicMock, clock: FakeClock
) -> None:
    """The clamp must not become "never settle": with room, the full window is
    still spent watching for the input to come back."""
    step = captcha_step(retries=1, timeout=5_000, error=None)
    reads = page(mock_session, step, input_attached=[False], clock=clock)
    read, _ = replying(ANSWER)
    start = clock.now

    result = solved(mock_session, step, read)

    assert isinstance(result, CaptchaResult)
    assert reads[-1] == (step.input, CAPTCHA_SETTLE_MS)
    assert clock.now - start == pytest.approx(CAPTCHA_SETTLE_MS / 1000.0)


FLOW = """
steps:
  - name: captcha
    action: solve_captcha
    image: "#captcha-img"
    input: "#captcha-answer"
    submit: "#submit"
    timeout: 0
"""


def test_a_flow_run_uses_the_registered_reader(mock_session: MagicMock) -> None:
    # The input is already gone, so the first poll reads as accepted.
    mock_session.element_exists.return_value = False
    read, seen = replying(ANSWER)
    captcha.set_reader(read)

    result = run_flow(mock_session, load_flow_text(FLOW), {})

    assert isinstance(result, FlowSuccess), result
    assert result.outputs == {"captcha": {"attempts": 1}}
    assert seen == [PNG]


def test_a_flow_run_with_no_reader_fails_asking_for_a_human(
    mock_session: MagicMock,
) -> None:
    mock_session.element_exists.return_value = False

    result = run_flow(mock_session, load_flow_text(FLOW), {})

    assert not isinstance(result, FlowSuccess)
    assert result.human_needed is True
