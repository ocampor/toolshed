"""The image captcha step: crop it, ask something that can read, type it back.

The library never reads the image itself. A caller injects a
:data:`CaptchaSolver` — a model sampling call, a human-in-the-loop prompt,
whatever it has — through ``run_flow(..., solver=)``, and this module owns the
loop around it: one crop per attempt, a normalized answer, and the page's own
verdict read back off the DOM.

The answer never leaves the step. It is typed into the page and dropped: not
in the result, not in a log line, not in an error message.
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING, Callable

from llm_browser.behavior import jittered_sleep
from llm_browser.constants import (
    DEFAULT_POLL_INTERVAL_MS,
    DEFAULT_SETTLE_MS,
    LOGGER_NAME,
)
from llm_browser.models import SolverMode
from llm_browser.results import ActionResult, CaptchaResult, ErrorResult
from llm_browser.waits import poll_jitter

if TYPE_CHECKING:
    from llm_browser.models import SolveCaptchaStep
    from llm_browser.session import BrowserSession

logger = logging.getLogger(LOGGER_NAME)

# ``(png_bytes, prompt) -> reply``. The reply is free text; ``normalize_answer``
# decides whether it is an answer at all.
CaptchaSolver = Callable[[bytes, str | None], str]

# What a captcha answer may look like once the punctuation is gone. The bounds
# are what real image captchas use, and they are also the guard that keeps a
# chatty model reply from being typed into the page.
ANSWER_PATTERN = re.compile(r"^[A-Za-z0-9]{3,12}$")

# The one word a solver says instead of guessing.
UNREADABLE = "unreadable"


def normalize_answer(reply: str) -> str | None:
    """What to type, or ``None`` when the reply is not an answer.

    One rule, applied to the whole reply: drop everything that is not a letter
    or a digit, and keep the result only if it is 3-12 characters and not
    ``UNREADABLE``. Nothing is *extracted* — a solver that explains itself has
    failed the attempt, which is why the prompt asks for the characters alone.
    """
    stripped = re.sub(r"[^A-Za-z0-9]", "", reply)
    if stripped.casefold() == UNREADABLE:
        return None
    return stripped if ANSWER_PATTERN.match(stripped) else None


def failed(
    step: SolveCaptchaStep, message: str, *, human_needed: bool = False
) -> ErrorResult:
    return ErrorResult(
        error="CaptchaUnsolved",
        message=message,
        step_name=step.name,
        selector=repr(step.image),
        human_needed=human_needed,
    )


def missing_solver_error(step: SolveCaptchaStep) -> ErrorResult:
    """Why this step has no solver to call.

    ``sampling`` asked for one and the client wired none, which is a caller
    bug. ``human`` and a solverless ``auto`` are the same answer: a person has
    to look at the page.
    """
    if step.solver is SolverMode.SAMPLING:
        return failed(
            step, "solver mode 'sampling': the client did not provide a solver"
        )
    return failed(step, "no captcha solver available", human_needed=True)


def ask(solver: CaptchaSolver, png: bytes, prompt: str | None) -> str:
    """A solver is the caller's code; anything it raises is this step failing
    rather than the run unwinding."""
    try:
        return solver(png, prompt)
    except Exception as exc:
        raise ValueError(
            f"captcha solver raised {type(exc).__name__}: "
            f"{' '.join(str(exc).split())[:200]}"
        ) from exc


def error_showing(session: BrowserSession, step: SolveCaptchaStep) -> bool:
    return step.error is not None and session.element_exists(
        step.error, timeout=0, state="visible"
    )


def gone_for_good(session: BrowserSession, step: SolveCaptchaStep) -> bool:
    """Whether the input that just left the DOM stays gone.

    A form that reloads takes its input away for a moment on the way back, so
    a single "not there" read is not the form moving on. Waiting for it to
    come back is the same question upside down: nothing within ``settle``
    means it really is gone.
    """
    return not session.element_exists(step.input, timeout=DEFAULT_SETTLE_MS)


def accepted(
    session: BrowserSession, step: SolveCaptchaStep, stale_error: bool
) -> bool:
    """Poll the page for its verdict on the answer just submitted.

    ``stale_error`` is whether the error was already showing before this
    answer went in. A banner the page never cleared is not a verdict on this
    attempt — believing one is how a correct second answer gets reported as a
    failure — so a stale banner only counts once a reload has put a fresh one
    up.

    ``True`` when the input is gone for good, ``False`` on a rejection and
    ``False`` again if neither happens within ``timeout``: an undecided page
    is a failed attempt, not a hang.
    """
    deadline = time.monotonic() + step.timeout / 1000.0
    pause = poll_jitter(DEFAULT_POLL_INTERVAL_MS)
    reloaded = False
    while True:
        if not session.element_exists(step.input, timeout=0):
            if gone_for_good(session, step):
                return True
            reloaded = True
        elif error_showing(session, step) and (not stale_error or reloaded):
            return False
        if time.monotonic() >= deadline:
            return False
        jittered_sleep(pause, session.behavior_runtime.rng)


def one_attempt(
    session: BrowserSession, step: SolveCaptchaStep, solver: CaptchaSolver
) -> bool:
    """One crop, one answer, one verdict.

    The crop is taken per attempt because a rejected captcha is usually a new
    image. A reply that is not an answer spends the attempt without touching
    the form.
    """
    answer = normalize_answer(
        ask(solver, session.screenshot_bytes(step.image), step.prompt)
    )
    if answer is None:
        return False
    stale_error = error_showing(session, step)
    session.fill(step.input, answer)
    if step.submit is not None:
        session.click(step.submit)
    return accepted(session, step, stale_error)


def solve(session: BrowserSession, step: SolveCaptchaStep) -> ActionResult:
    solver = None if step.solver is SolverMode.HUMAN else step._solver
    if solver is None:
        return missing_solver_error(step)
    for attempt in range(1, step.retries + 1):
        if one_attempt(session, step, solver):
            return CaptchaResult(attempts=attempt, solver=step.solver.value)
        logger.debug("captcha attempt %d of %d rejected", attempt, step.retries)
    return failed(
        step,
        f"captcha not solved in {step.retries} attempts",
        human_needed=True,
    )
