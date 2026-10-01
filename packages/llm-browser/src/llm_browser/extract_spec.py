"""What one typed ``read`` field asks for, validated once at flow load."""

import re
import time
import warnings
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from llm_browser import constants


class ExtractSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    child_selector: str | None = None
    attribute: str = constants.DEFAULT_EXTRACT_ATTRIBUTE
    pattern: re.Pattern[str] | None = None
    type: Literal["str", "int", "float", "date"] = "str"
    required: bool = False
    format: str | None = Field(None, max_length=64)
    date_order: Literal["MDY", "DMY", "YMD"] = "MDY"
    languages: tuple[str, ...] = Field(("en",), min_length=1, max_length=8)

    @field_validator("pattern", mode="before")
    @classmethod
    def compiled(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        try:
            return re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid pattern {value!r}: {exc}") from exc

    @model_validator(mode="after")
    def date_options_need_date(self) -> Self:
        stray = sorted(self.model_fields_set & {"format", "date_order", "languages"})
        if stray and self.type != "date":
            raise ValueError(f"{stray} apply only to type: date, not {self.type}")
        return self

    @field_validator("format")
    @classmethod
    def known_format(cls, value: str | None) -> str | None:
        return None if value is None else check_format(value)

    @field_validator("languages")
    @classmethod
    def known_languages(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return check_languages(value)


def check_format(date_format: str) -> str:
    """A directive strptime does not know fails here, at flow load."""
    try:
        # A year-less format like "%d" warns on 3.13; only its directives matter here.
        with warnings.catch_warnings(action="ignore", category=DeprecationWarning):
            time.strptime(time.strftime(date_format), date_format)
    except ValueError as exc:
        raise ValueError(f"invalid date format {date_format!r}: {exc}") from exc
    return date_format


def check_languages(languages: tuple[str, ...]) -> tuple[str, ...]:
    # Imported here: dateparser costs ~80 ms an import that reads no date skips.
    from dateparser.languages.loader import default_loader

    try:
        default_loader.get_locale_map(languages=list(languages))
    except ValueError as exc:
        raise ValueError(f"invalid date languages {list(languages)}: {exc}") from exc
    return languages
