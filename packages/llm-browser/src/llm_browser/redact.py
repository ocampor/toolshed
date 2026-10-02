"""Replace injected secret values with a placeholder before they escape."""

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from types import UnionType
from typing import Annotated, Any, TypeAliasType, Union, get_args, get_origin

from pydantic import BaseModel

from llm_browser.constants import LOGGER_NAME, REDACTED

TYPED_LEAF = (int, float, Decimal, date)


def redact_secrets(value: Any, secrets: Sequence[str]) -> Any:
    """Rebuilds containers and models with their original type, so callers
    keep typed results (``FlowError.data`` stays an ``ActionResult``)."""
    if not secrets:
        return value
    match value:
        case str():
            return _redact_text(value, secrets)
        case bool():
            return value
        case _ if isinstance(value, TYPED_LEAF):
            return REDACTED if _leaks(leaf_text(value), secrets) else value
        case BaseModel():
            updates = {
                k: redact_secrets(v, secrets)
                for k, v in value
                if not declared_number(value, k)
            }
            return value.model_copy(update=updates)
        case dict():
            return {k: redact_secrets(v, secrets) for k, v in value.items()}
        case list():
            return [redact_secrets(v, secrets) for v in value]
        case tuple():
            return tuple(redact_secrets(v, secrets) for v in value)
        case _:
            return value


def declared_number(model: BaseModel, name: str) -> bool:
    """A field typed as a number (``row``, ``found``) is schema, never page
    data; ``object`` fields and extras still carry page or caller values."""
    field = type(model).model_fields.get(name)
    if field is None:
        return False
    annotation = field.annotation
    if isinstance(annotation, TypeAliasType):
        annotation = annotation.__value__
    if get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]
    # Only unions are unwrapped: a ``list[int]`` field holds data, not schema.
    is_union = get_origin(annotation) in (Union, UnionType)
    members = get_args(annotation) if is_union else (annotation,)
    return any(isinstance(m, type) and issubclass(m, TYPED_LEAF) for m in members)


def _redact_text(text: str, secrets: Sequence[str]) -> str:
    for secret in secrets:
        text = text.replace(secret, REDACTED)
    return text


def leaf_text(value: float | Decimal | date) -> str:
    return value.isoformat() if isinstance(value, date) else str(value)


def _leaks(text: str, secrets: Sequence[str]) -> bool:
    # A typed read stores "4,180" as 4180, so compare the secret without commas.
    return any(s in text or s.replace(",", "") in text for s in secrets)


def clean_secrets(secrets: Any) -> list[str]:
    """Empty secrets are dropped — replacing ``""`` would shred every
    string."""
    return [str(s) for s in secrets if s]


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: Sequence[str]) -> None:
        super().__init__()
        self.secrets = secrets

    def filter(self, record: logging.LogRecord) -> bool:
        # Formatted first: a masked number arg would break a ``%d``.
        try:
            message = record.getMessage()
        except TypeError:
            message = str(record.msg)
        record.msg = redact_secrets(message, self.secrets)
        record.args = None
        return True


@contextmanager
def redacting_logs(secrets: Sequence[str]) -> Iterator[None]:
    """The filter sits on the package logger, so it covers the session and
    actions as well as the runner."""
    # debt: package-wide filter; a concurrent run in another thread is
    # scrubbed too (harmless, never leaks).
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
