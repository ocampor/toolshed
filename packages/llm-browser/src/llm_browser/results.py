"""What an action produced. Nothing here is a path: the library keeps its
output in memory and the caller decides whether any of it reaches disk."""

import base64
import mimetypes
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
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


def is_timeout(exc: BaseException) -> bool:
    """Treat any exception class named ``TimeoutError`` as a timeout.
    Patchright (and similar driver libs) raise their own TimeoutError
    that does NOT inherit from the Python builtin, so a bare
    ``isinstance(exc, TimeoutError)`` check misses driver-side waits
    and the optional-swallow / ErrorResult contract was violated."""
    if isinstance(exc, TimeoutError):
        return True
    return type(exc).__name__ == "TimeoutError"


def is_step_failure(exc: BaseException) -> bool:
    """Whether ``exc`` is a step result rather than a library bug.

    Deliberately narrow. Anything a step can legitimately hit — a wait that
    expired, a value the page did not provide, an output it cannot write — is
    raised as one of these two at the place it happens. A ``TypeError`` or an
    ``AttributeError`` reaching here is a bug in the library, and it belongs
    in a traceback rather than in a truncated ``reason=`` on a skipped step.
    """
    return is_timeout(exc) or isinstance(exc, ValueError)


type PickSpec = Literal["first", "last"] | int


class AcceptedMatch(BaseModel):
    """A count mismatch a step's ``pick`` took instead of failing on."""

    expected: int | Literal["many"]
    found: int
    picked: PickSpec


class ExtractError(BaseModel):
    """A field a typed ``read`` could not fill, as pydantic reported it;
    ``step`` is filled in when the run records it."""

    step: str = ""
    row: int
    field: str
    msg: str
    input: str | None = None


class ActionResult(BaseModel):
    """Base for everything ``execute_action`` returns.

    All result subclasses inherit ``ok``: ``True`` for success/skip,
    ``False`` for ``ErrorResult``. The flow runner short-circuits when it
    sees a non-ok result.
    """

    ok: bool = True
    accepted: AcceptedMatch | None = None


class VoidResult(ActionResult):
    """Action succeeded with no payload (click, fill, select, press, ...)."""


class HitTarget(BaseModel):
    """The element the pointer was actually over when a click fired — the
    target or a descendant of it, since a humanized click that ends over
    anything else fails instead."""

    tag: str
    text: str = ""
    class_name: str = ""


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


class TextPage(BaseModel):
    page: int = Field(description="1-based.")
    text: str = Field(description='The page\'s text layer; "" when it has none.')
    clipped: bool = Field(
        default=False,
        description="`max_chars` cut this page short; request it alone with a larger one.",
    )


class ImagePage(BaseModel):
    page: int = Field(description="1-based; a frame, for a multi-frame image.")
    image: PayloadBytes = Field(description="JPEG bytes; base64 in JSON.")
    width: int
    height: int
    original_width: int = Field(
        description="PDF points for a PDF, pixels for an image."
    )
    original_height: int = Field(
        description="PDF points for a PDF, pixels for an image."
    )


class DocumentResult(ActionResult):
    """A download's ``extract:`` output: file metadata plus pages, instead of
    the bytes. ``pages`` is empty when the file has nothing the mode reads.

    ``truncated`` means a budget cut the run short: ``next_pages`` is the
    ``pages`` value that picks up where it stopped, and a page marked
    ``clipped`` is read in full only by requesting it alone with a larger
    ``max_chars`` (or in ``images`` mode).
    """

    filename: str = Field(description="The server's suggested name; remote input.")
    content_type: str
    size: int = Field(description="Bytes of the downloaded file.")
    sha256: str = Field(description="Hex digest of the downloaded file.")
    mode: Literal["text", "images"]
    page_count: int | None = Field(
        description="Pages (or frames, or text chunks) in the file; null with no pages."
    )
    truncated: bool
    next_pages: str | None = Field(description="Feed back as `pages` to continue.")
    pages: list[TextPage | ImagePage]


def guess_media_type(name: str) -> str:
    """The media type ``name``'s extension implies, or the generic one."""
    return mimetypes.guess_type(name)[0] or DEFAULT_MEDIA_TYPE


class TextResult(ActionResult):
    """Action produced inline text (dom, wait)."""

    text: str


class ExtractedRow(BaseModel, extra="allow"):
    """A single row of data extracted by ``read``. Field set is dynamic — keys
    come from the step's ``extract`` config; values are ``str``, ``int``,
    ``float``, ``date``, ``datetime`` or ``None``.
    Modeled with ``extra='allow'`` so it serializes uniformly while staying
    schema-free.
    """


class ParsedResult(ActionResult):
    """Action extracted structured rows.

    For ``read`` action: rows are ``ExtractedRow`` (dynamic-fields BaseModel),
    or ``None`` if every field read null.

    For ``parse`` action: rows are typed instances of the schema model
    (``ParseBase`` subclass), with values coerced by Pydantic.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    rows: list[SerializeAsAny[BaseModel] | None]
    extract_errors: list[ExtractError] = []


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
    # Set for a ``selectors.MatchError`` only: what the step asked for (``None``
    # when only its ``pick`` was out of reach), what the page had, and the text
    # of the first few matches.
    expected: int | Literal["many"] | None = None
    found: int | None = None
    samples: list[str] | None = None
