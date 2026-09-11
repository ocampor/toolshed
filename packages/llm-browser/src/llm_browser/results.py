"""What an action produced. Nothing here is a path: the library keeps its
output in memory and the caller decides whether any of it reaches disk."""

import base64
import mimetypes
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    PlainSerializer,
    SerializeAsAny,
)

DEFAULT_MEDIA_TYPE = "application/octet-stream"


def decode_base64_text(value: Any) -> Any:
    """Decode what the JSON serializer wrote, and only that.

    A JSON round-trip hands the field back the base64 ``str`` it dumped, so
    validating that has to reverse it. Raw ``bytes`` are already the payload:
    decoding those again is how ``pydantic.Base64Bytes`` silently turns a PNG
    into six bytes of garbage, which is why this type exists instead.
    """
    if isinstance(value, str):
        return base64.b64decode(value, validate=True)
    return value


def encode_base64_text(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


# Bytes in memory, base64 on the wire, and `model_validate(model_dump(mode=
# "json"))` gives back what went in.
PayloadBytes = Annotated[
    bytes,
    BeforeValidator(decode_base64_text),
    PlainSerializer(encode_base64_text, return_type=str, when_used="json"),
]


class ActionResult(BaseModel):
    """Base for everything ``execute_action`` returns.

    All result subclasses inherit ``ok``: ``True`` for success/skip,
    ``False`` for ``ErrorResult``. The flow runner short-circuits when it
    sees a non-ok result.
    """

    ok: bool = True


class VoidResult(ActionResult):
    """Action succeeded with no payload (click, fill, select, press, ...)."""


class BytesResult(ActionResult):
    """Bytes an action produced — a screenshot, a downloaded file.

    ``name`` is what the file would be called (the server's suggested
    filename for a download), not a place it was written — and it is remote
    input, so anything writing it to disk takes its basename first. The bytes
    stay bytes in memory; only ``model_dump(mode="json")`` turns them into
    base64, so a JSON consumer gets something transportable and a Python
    caller gets the real payload. Validating that JSON back decodes it, so the
    model round-trips.

    The payload is held whole in memory, with no size ceiling: a caller
    fetching something large should expect it, plus a further ~4/3 of it if it
    then dumps to JSON.
    """

    name: str
    content: PayloadBytes
    media_type: str = DEFAULT_MEDIA_TYPE


def guess_media_type(name: str) -> str:
    """The media type ``name``'s extension implies, or the generic one."""
    return mimetypes.guess_type(name)[0] or DEFAULT_MEDIA_TYPE


class TextResult(ActionResult):
    """Action produced inline text (dom, wait)."""

    text: str


class ExtractedRow(BaseModel, extra="allow"):
    """A single row of data extracted by ``read``. Field set is dynamic — keys
    come from the step's ``extract`` config; values are ``str`` or ``None``.
    Modeled with ``extra='allow'`` so it serializes uniformly while staying
    schema-free.
    """


class ParsedResult(ActionResult):
    """Action extracted structured rows.

    For ``read`` action: rows are ``ExtractedRow`` (dynamic-fields BaseModel),
    or ``None`` if every field was empty for that row.

    For ``parse`` action: rows are typed instances of the schema model
    (``ParseBase`` subclass), with values coerced by Pydantic.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    rows: list[SerializeAsAny[BaseModel] | None]


class SkippedResult(ActionResult):
    """Optional step was skipped because its action raised an expected error.
    ``ok`` stays True — a skip is a successful no-op."""

    skipped: bool = True
    reason: str


class ErrorResult(ActionResult):
    """Action failed with an expected runtime error (Timeout/Value).

    Returned (not raised) so the flow runner can short-circuit cleanly and
    the CLI can emit structured JSON without unwinding through Python's
    exception machinery. Truly unexpected exceptions still propagate.
    """

    ok: bool = False
    error: str
    message: str
    step_name: str
    selector: str | None = None
    hint: str | None = None
