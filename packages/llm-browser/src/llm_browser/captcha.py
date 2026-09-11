"""The image captcha step: crop it, read it, type it back.

The library never reads the image itself. The host process registers one
:data:`CaptchaReader` with :func:`set_reader` — a model sampling call, a
prompt to a person, whatever it has — and this module owns the loop around it:
one crop per attempt, a normalized answer, and the page's own verdict read back
off the DOM. One step, one reader: a different way of reading an image is a
different step, not a parameter on this one.

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
    CAPTCHA_SETTLE_MS,
    DEFAULT_POLL_INTERVAL_MS,
    LOGGER_NAME,
)
from llm_browser.results import ActionResult, CaptchaResult, ErrorResult
from llm_browser.waits import poll_jitter

if TYPE_CHECKING:
    from llm_browser.models import SolveCaptchaStep
    from llm_browser.session import BrowserSession

logger = logging.getLogger(LOGGER_NAME)

# ``(png_bytes, prompt) -> reply``. The reply is free text; ``normalize_answer``
# decides whether it is an answer at all.
CaptchaReader = Callable[[bytes, str | None], str]

# Process-wide on purpose: reading a captcha is a capability the host either
# has or does not, not something one flow run can differ on.
_reader: CaptchaReader | None = None


class ReaderUnavailable(Exception):
    """Raise from a reader when no reading is possible in this run."""


# What a captcha answer may look like once the punctuation is gone. The bounds
# are what real image captchas use, and they are also the guard that keeps a
# chatty model reply from being typed into the page.
ANSWER_PATTERN = re.compile(r"^[A-Za-z0-9]{3,12}$")

# The one word a reader says instead of guessing.
UNREADABLE = "unreadable"


def set_reader(new_reader: CaptchaReader | None) -> None:
    """Register the function ``solve_captcha`` reads images with, or clear it.

    Nothing is registered by default — ``llm-browser`` the CLI registers
    nothing at all — so an unconfigured process reports every captcha as
    needing a human instead of guessing at one.
    """
    global _reader
    _reader = new_reader


def reader() -> CaptchaReader | None:
    return _reader


def normalize_answer(reply: str) -> str | None:
    """What to type, or ``None`` when the reply is not an answer.

    One rule, applied to the whole reply: drop everything that is not a letter
    or a digit, and keep the result only if it is 3-12 characters and not
    ``UNREADABLE``. Nothing is *extracted* — a reader that explains itself has
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


def ask(read: CaptchaReader, png: bytes, prompt: str | None) -> str:
    """A reader is the host's code; anything it raises is this step failing
    rather than the run unwinding."""
    try:
        return read(png, prompt)
    except ReaderUnavailable:
        raise
    except Exception as exc:
        raise ValueError(
            f"captcha reader raised {type(exc).__name__}: "
            f"{' '.join(str(exc).split())[:200]}"
        ) from exc


def error_showing(session: BrowserSession, step: SolveCaptchaStep) -> bool:
    return step.error is not None and session.element_exists(
        step.error, timeout=0, state="visible"
    )


def gone_for_good(
    session: BrowserSession, step: SolveCaptchaStep, deadline: float
) -> bool:
    """Whether the input that just left the DOM stays gone.

    A reloading form takes its input away for a moment on the way back, so one
    "not there" read is not the form moving on. Waiting for it to come back is
    the same question upside down: nothing within the settle window means it
    really is gone.

    The window is whatever is left of the verdict's budget, capped at
    ``CAPTCHA_SETTLE_MS``. ``timeout`` bounds the whole verdict, so a tight one
    degrades to no confirmation rather than to a late one — with none left, the
    read that got us here is the answer.
    """
    settle_ms = min(CAPTCHA_SETTLE_MS, int((deadline - time.monotonic()) * 1000))
    if settle_ms <= 0:
        return True
    return not session.element_exists(step.input, timeout=settle_ms)


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
            if gone_for_good(session, step, deadline):
                return True
            reloaded = True
        elif error_showing(session, step) and (not stale_error or reloaded):
            return False
        if time.monotonic() >= deadline:
            return False
        jittered_sleep(pause, session.behavior_runtime.rng)


def one_attempt(
    session: BrowserSession, step: SolveCaptchaStep, read: CaptchaReader
) -> bool:
    """One crop, one answer, one verdict.

    The crop is taken per attempt because a rejected captcha is usually a new
    image. A reply that is not an answer spends the attempt without touching
    the form.
    """
    answer = normalize_answer(
        ask(read, session.screenshot_bytes(step.image), step.prompt)
    )
    if answer is None:
        return False
    stale_error = error_showing(session, step)
    session.fill(step.input, answer)
    if step.submit is not None:
        session.click(step.submit)
    return accepted(session, step, stale_error)


def solve(session: BrowserSession, step: SolveCaptchaStep) -> ActionResult:
    read = reader()
    if read is None:
        # Before the page is touched: nothing here can succeed, and a crop
        # nobody will look at is wasted work on a site watching for it.
        return failed(step, "no captcha reader is configured", human_needed=True)
    try:
        for attempt in range(1, step.retries + 1):
            if one_attempt(session, step, read):
                return CaptchaResult(attempts=attempt)
            logger.debug("captcha attempt %d of %d rejected", attempt, step.retries)
    except ReaderUnavailable:
        # Not a wrong answer: the reader has said it cannot look at all, so
        # the remaining retries would only spend crops on the same refusal.
        return failed(
            step, "no captcha reader available in this run", human_needed=True
        )
    return failed(
        step,
        f"captcha not solved in {step.retries} attempts",
        human_needed=True,
    )
