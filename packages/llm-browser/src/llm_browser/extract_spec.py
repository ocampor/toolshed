"""What one typed ``read`` field asks for, validated once at flow load."""

import re
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
