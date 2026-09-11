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
from enum import StrEnum
from typing import TYPE_CHECKING, Callable

from llm_browser.constants import DEFAULT_POLL_INTERVAL_MS, LOGGER_NAME
from llm_browser.results import ActionResult, CaptchaResult, ErrorResult

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


class SolverMode(StrEnum):
    """Who is allowed to read the image."""

    AUTO = "auto"
    SAMPLING = "sampling"
    HUMAN = "human"


def normalize_answer(reply: str) -> str | None:
    """What to type, or ``None`` when the reply is not an answer.

    Punctuation and whitespace go: a solver that answers ``"7 F K 2 Q"`` or
    ``"The code is: 7fkq2."`` means the same five characters.
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


def accepted(session: BrowserSession, step: SolveCaptchaStep) -> bool:
    """Poll the page for its verdict until ``timeout`` runs out.

    ``True`` once the input is gone — the form moved on. ``False`` as soon as
    the page shows its error, and ``False`` again if neither happens in time:
    an undecided page is a failed attempt, not a hang.
    """
    deadline = time.monotonic() + step.timeout / 1000.0
    while True:
        if step.error is not None and session.element_exists(
            step.error, timeout=0, state="visible"
        ):
            return False
        if not session.element_exists(step.input, timeout=0):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(DEFAULT_POLL_INTERVAL_MS / 1000.0)


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
    session.fill(step.input, answer)
    if step.submit is not None:
        session.click(step.submit)
    return accepted(session, step)


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
