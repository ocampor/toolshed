"""The ``solve_captcha`` step: the loop around a solver the caller injects."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from llm_browser import captcha
from llm_browser.actions import execute_action
from llm_browser.captcha import CaptchaSolver, normalize_answer
from llm_browser.flows import load_flow_text, run_flow
from llm_browser.models import FlowSuccess, SolveCaptchaStep, SolverMode
from llm_browser.results import CaptchaResult, ErrorResult

PNG = b"\x89PNG\r\n\x1a\nfake"
ANSWER = "7fkq2"


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


def replying(*replies: str) -> tuple[CaptchaSolver, list[bytes]]:
    """A solver walking ``replies``, plus the crops it was shown."""
    seen: list[bytes] = []
    remaining = list(replies)

    def solver(png: bytes, prompt: str | None) -> str:
        seen.append(png)
        return remaining.pop(0)

    return solver, seen


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """The verdict poll's pause between ticks; no test should pay for it."""
    monkeypatch.setattr(captcha, "jittered_sleep", lambda jitter, rng: None)


def page(
    session: MagicMock,
    step: SolveCaptchaStep,
    *,
    input_attached: list[bool],
    error_visible: list[bool] | None = None,
) -> None:
    """Script what the page answers, per selector, read in turn.

    Each list is consumed one read at a time and its last value then repeats,
    so a test says only as much about the page as it cares about. ``input`` is
    asked both by the verdict poll and by the settle re-check; ``error`` both
    before the answer goes in (is the banner stale?) and during the poll.
    """
    queues = {
        step.input: list(input_attached),
        step.error: list(error_visible or [False]),
    }

    def exists(selector: Any, timeout: int = 0, *, state: str = "attached") -> bool:
        queue = queues[selector]
        return queue.pop(0) if len(queue) > 1 else queue[0]

    session.element_exists.side_effect = exists


def solved(session: MagicMock, step: SolveCaptchaStep, solver: CaptchaSolver) -> Any:
    step._solver = solver
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
    solver, seen = replying(ANSWER)

    result = solved(mock_session, step, solver)

    assert isinstance(result, CaptchaResult)
    assert result.attempts == 1
    assert result.solver == "auto"
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
    solver, seen = replying("wrong", ANSWER)

    result = solved(mock_session, step, solver)

    assert isinstance(result, CaptchaResult)
    assert result.attempts == 2
    assert seen == [b"first-crop", b"second-crop"], "the second attempt reused a crop"


def test_running_out_of_retries_asks_for_a_human(mock_session: MagicMock) -> None:
    step = captcha_step(retries=2)
    page(mock_session, step, input_attached=[True], error_visible=[False, True])
    solver, _ = replying(ANSWER, ANSWER)

    result = solved(mock_session, step, solver)

    assert isinstance(result, ErrorResult)
    assert result.human_needed is True
    assert "2 attempts" in result.message


def test_an_unreadable_reply_spends_the_attempt_without_typing(
    mock_session: MagicMock,
) -> None:
    step = captcha_step(retries=1)
    solver, _ = replying("UNREADABLE")

    result = solved(mock_session, step, solver)

    assert isinstance(result, ErrorResult)
    assert result.human_needed is True
    mock_session.fill.assert_not_called()


def test_solver_mode_human_never_calls_the_solver(mock_session: MagicMock) -> None:
    step = captcha_step(solver=SolverMode.HUMAN)
    calls: list[bytes] = []

    def solver(png: bytes, prompt: str | None) -> str:
        calls.append(png)
        return ANSWER

    result = solved(mock_session, step, solver)

    assert isinstance(result, ErrorResult)
    assert result.human_needed is True
    assert calls == []
    mock_session.screenshot_bytes.assert_not_called()


def test_solver_mode_sampling_without_a_solver_names_the_client(
    mock_session: MagicMock,
) -> None:
    step = captcha_step(solver=SolverMode.SAMPLING)

    result = execute_action(mock_session, step)

    assert isinstance(result, ErrorResult)
    assert "did not provide a solver" in result.message
    assert result.human_needed is False, "a missing injection is a caller bug"


def test_a_solver_that_raises_fails_the_step_instead_of_the_run(
    mock_session: MagicMock,
) -> None:
    step = captcha_step()

    def solver(png: bytes, prompt: str | None) -> str:
        raise RuntimeError("sampling API is down")

    result = solved(mock_session, step, solver)

    assert isinstance(result, ErrorResult)
    assert "sampling API is down" in result.message


def test_the_answer_never_reaches_the_result(mock_session: MagicMock) -> None:
    step = captcha_step()
    page(mock_session, step, input_attached=[False])
    solver, _ = replying(ANSWER)

    result = solved(mock_session, step, solver)

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
    solver, _ = replying(ANSWER)

    result = solved(mock_session, step, solver)

    assert isinstance(result, CaptchaResult)
    assert result.attempts == 1


def test_a_banner_that_appears_after_the_answer_is_a_rejection(
    mock_session: MagicMock,
) -> None:
    """The single-page case: no reload, the banner simply was not there
    before and is now."""
    step = captcha_step(retries=1)
    page(mock_session, step, input_attached=[True], error_visible=[False, True])
    solver, _ = replying(ANSWER)

    result = solved(mock_session, step, solver)

    assert isinstance(result, ErrorResult)
    assert result.human_needed is True


def test_a_reload_that_puts_the_banner_back_up_is_a_rejection(
    mock_session: MagicMock, no_sleep: None
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
    )
    solver, _ = replying(ANSWER)

    result = solved(mock_session, step, solver)

    assert isinstance(result, ErrorResult)
    assert result.human_needed is True


def test_an_input_that_only_flickered_is_not_acceptance(
    mock_session: MagicMock,
) -> None:
    """Acceptance is the input staying gone, not one lucky read of it."""
    step = captcha_step(retries=1, timeout=0, error=None)
    page(mock_session, step, input_attached=[False, True])
    solver, _ = replying(ANSWER)

    result = solved(mock_session, step, solver)

    assert isinstance(result, ErrorResult)


FLOW = """
steps:
  - name: captcha
    action: solve_captcha
    image: "#captcha-img"
    input: "#captcha-answer"
    submit: "#submit"
    timeout: 0
"""


def test_run_flow_hands_its_solver_to_the_step(mock_session: MagicMock) -> None:
    # The input is already gone, so the first poll reads as accepted.
    mock_session.element_exists.return_value = False
    solver, seen = replying(ANSWER)

    result = run_flow(mock_session, load_flow_text(FLOW), {}, solver=solver)

    assert isinstance(result, FlowSuccess), result
    assert result.outputs == {"captcha": {"attempts": 1, "solver": "auto"}}
    assert seen == [PNG]


def test_a_flow_with_no_solver_fails_asking_for_a_human(
    mock_session: MagicMock,
) -> None:
    mock_session.element_exists.return_value = False

    result = run_flow(mock_session, load_flow_text(FLOW), {})

    assert not isinstance(result, FlowSuccess)
    assert result.human_needed is True
