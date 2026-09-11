"""What an action produced. Nothing here is a path: the library keeps its
output in memory and the caller decides whether any of it reaches disk."""

import base64
import mimetypes

from pydantic import BaseModel, ConfigDict, SerializeAsAny, field_serializer

DEFAULT_MEDIA_TYPE = "application/octet-stream"


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
    filename for a download), not a place it was written. The bytes stay
    bytes in memory; only ``model_dump(mode="json")`` turns them into
    base64, so a JSON consumer gets something transportable and a Python
    caller gets the real payload.
    """

    name: str
    content: bytes
    media_type: str = DEFAULT_MEDIA_TYPE

    @field_serializer("content", when_used="json")
    def serialize_content(self, content: bytes) -> str:
        return base64.b64encode(content).decode("ascii")


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
