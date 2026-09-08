"""Replace injected secret values with a placeholder before they escape."""

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from pydantic import BaseModel

from llm_browser.constants import LOGGER_NAME, REDACTED


def redact_secrets(value: Any, secrets: Sequence[str]) -> Any:
    """Return ``value`` with every occurrence of every secret replaced
    by ``***``.

    Walks strings, containers and pydantic models, rebuilding each one
    with the same shape and type so callers keep their typed results
    (``FlowError.data`` stays an ``ActionResult``). Empty secrets are
    ignored — replacing ``""`` would shred every string.
    """
    if not secrets:
        return value
    match value:
        case str():
            return _redact_text(value, secrets)
        case BaseModel():
            updates = {k: redact_secrets(v, secrets) for k, v in value}
            return value.model_copy(update=updates)
        case dict():
            return {k: redact_secrets(v, secrets) for k, v in value.items()}
        case list():
            return [redact_secrets(v, secrets) for v in value]
        case tuple():
            return tuple(redact_secrets(v, secrets) for v in value)
        case _:
            return value


def _redact_text(text: str, secrets: Sequence[str]) -> str:
    for secret in secrets:
        text = text.replace(secret, REDACTED)
    return text


def clean_secrets(secrets: Any) -> list[str]:
    """Normalize a caller-supplied ``redact`` argument into the list of
    non-empty secret strings to scrub."""
    return [str(s) for s in secrets if s]


class RedactingFilter(logging.Filter):
    """Scrub secrets from a log record's message and args in place."""

    def __init__(self, secrets: Sequence[str]) -> None:
        super().__init__()
        self.secrets = secrets

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_secrets(record.msg, self.secrets)
        record.args = redact_secrets(record.args, self.secrets)
        return True


@contextmanager
def redacting_logs(secrets: Sequence[str]) -> Iterator[None]:
    """Scrub secrets from every ``llm_browser`` log record emitted in
    this block.

    The filter sits on the package logger, so it covers records from the
    session and actions as well as the runner itself.
    """
    # debt: package-wide filter; a concurrent run in another thread with
    # different secrets would also be scrubbed (harmless, never leaks).
    if not secrets:
        yield
        return
    logger = logging.getLogger(LOGGER_NAME)
    log_filter = RedactingFilter(secrets)
    logger.addFilter(log_filter)
    try:
        yield
    finally:
        logger.removeFilter(log_filter)
