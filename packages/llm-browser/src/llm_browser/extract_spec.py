"""What one ``read`` extract field asks for, and how its raw text becomes a value."""

import datetime
import re
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    TypeAdapter,
    field_validator,
)

from llm_browser import constants

# Without them dateparser fills a missing day or month from the run's date:
# "marzo 2026" would read as the 15th on the 15th.
REQUIRED_DATE_PARTS = ["day", "month"]


class BaseSpec(BaseModel):
    """Where the value is and the ``pattern`` that picks it; subclasses convert."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    child_selector: str | None = None
    attribute: str = constants.DEFAULT_EXTRACT_ATTRIBUTE
    pattern: re.Pattern[str] | None = None
    required: bool = False
    type: str

    default_pattern: ClassVar[re.Pattern[str] | None] = None

    @field_validator("pattern", mode="before")
    @classmethod
    def compiled(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        try:
            return re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid pattern {value!r}: {exc}") from exc

    def checked(self, raw: str | None) -> Any:
        """The value, as a row model's validator; ``required`` turns nothing read into an error."""
        value = self.value(raw)
        if value is None and self.required:
            raise ValueError(f"required, nothing read from {raw!r}")
        return value

    def value(self, raw: str | None) -> Any:
        """``None`` when there is nothing to read; a ``ValueError`` when the text will not convert."""
        if raw is None:
            return None
        picked = self.picked(raw)
        if picked is None:
            return None
        return self.convert(picked)

    def picked(self, raw: str) -> str | None:
        """Group 1 when the pattern has one, else the whole match; an optional
        group 1 that matched nothing is no match too."""
        pattern = self.pattern or self.default_pattern
        if pattern is None:
            return raw
        found = pattern.search(raw)
        if found is None:
            return None
        picked: str | None = found.group(1) if pattern.groups else found.group(0)
        return picked

    def convert(self, text: str) -> Any:
        return text


class StrSpec(BaseSpec):
    type: Literal["str"] = "str"


class NumberSpec(BaseSpec):
    """Thousands separators are US commas: ``"1,50"`` is 150."""

    default_pattern = re.compile(constants.NUMBER_PATTERN)

    def cast(self, text: str) -> Any:
        raise NotImplementedError

    def convert(self, text: str) -> Any:
        try:
            return self.cast(text.replace(",", "").strip())
        except ValueError:
            raise ValueError(f"could not convert {text!r} to {self.type}") from None


class IntSpec(NumberSpec):
    type: Literal["int"] = "int"

    def cast(self, text: str) -> Any:
        return int(text)


class FloatSpec(NumberSpec):
    type: Literal["float"] = "float"

    def cast(self, text: str) -> Any:
        return float(text)


class MomentSpec(BaseSpec):
    """``format`` reads that strptime format only; without it dateparser reads
    the text in ``languages``. Set ``date_order`` only for ambiguous numeric
    dates: dateparser applies it to ISO too."""

    format: str | None = Field(None, max_length=64)
    languages: tuple[str, ...] = Field(("en",), min_length=1, max_length=8)
    date_order: Literal["MDY", "DMY", "YMD"] | None = None

    def convert(self, text: str) -> Any:
        if not text.strip():
            return None
        parsed = self.parsed(text.strip())
        if parsed is None:
            raise ValueError(f"could not parse {text!r} as a {self.type}")
        return parsed

    def parsed(self, text: str) -> datetime.datetime | None:
        if self.format:
            return strict_datetime(text, self.format)
        # Imported here: dateparser costs ~80 ms an import that reads no date skips.
        import dateparser

        settings: dict[str, Any] = {"REQUIRE_PARTS": REQUIRED_DATE_PARTS}
        if self.date_order:
            settings["DATE_ORDER"] = self.date_order
        return dateparser.parse(text, languages=list(self.languages), settings=settings)


class DateTimeSpec(MomentSpec):
    type: Literal["datetime"] = "datetime"


class DateSpec(MomentSpec):
    type: Literal["date"] = "date"

    def convert(self, text: str) -> Any:
        parsed = super().convert(text)
        return None if parsed is None else parsed.date()


def strict_datetime(text: str, date_format: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.strptime(text, date_format)
    except ValueError:
        return None


def spec_type(value: Any) -> str:
    """A spec without ``type`` is a string."""
    if isinstance(value, dict):
        return str(value.get("type", "str"))
    return str(getattr(value, "type", "str"))


SPEC_CLASSES: tuple[type[BaseSpec], ...] = (
    StrSpec,
    IntSpec,
    FloatSpec,
    DateTimeSpec,
    DateSpec,
)

ExtractSpec = Annotated[
    Annotated[StrSpec, Tag("str")]
    | Annotated[IntSpec, Tag("int")]
    | Annotated[FloatSpec, Tag("float")]
    | Annotated[DateTimeSpec, Tag("datetime")]
    | Annotated[DateSpec, Tag("date")],
    Discriminator(spec_type),
]

EXTRACT_SPEC: TypeAdapter[ExtractSpec] = TypeAdapter(ExtractSpec)

SPEC_KEYS = frozenset(name for spec in SPEC_CLASSES for name in spec.model_fields)
