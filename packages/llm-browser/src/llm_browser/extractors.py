"""One pydantic metadata class per extract ``type``: pattern, then text, then
the type's own validation, with a failure kept as ``None`` plus a warning."""

import datetime
import re
from dataclasses import dataclass
from collections.abc import Callable
from functools import lru_cache
from typing import Any, ClassVar

from pydantic import GetCoreSchemaHandler, ValidationError, ValidationInfo
from pydantic_core import core_schema
from yaml_engine.registry import Registry

from llm_browser.constants import NUMBER_PATTERN
from llm_browser.extract_dates import parsed_date
from llm_browser.extract_spec import ExtractSpec
from llm_browser.results import ExtractWarning


@lru_cache(maxsize=1)
def get_extractors() -> Registry[type["Extractor"]]:
    return Registry("extract type")


def matched(raw: str, pattern: re.Pattern[str]) -> str | None:
    """Group 1 when the pattern has one, else the whole match; an optional
    group 1 that matched nothing is no match too."""
    found = pattern.search(raw)
    if found is None:
        return None
    picked: str | None = found.group(1) if pattern.groups else found.group(0)
    return picked


def numeric_text(text: str) -> str:
    return text.replace(",", "").strip()


def converted(matched: str, convert: Callable[[str], Any]) -> Any:
    try:
        return convert(numeric_text(matched))
    except ValueError:
        raise ValueError(
            f"could not convert {matched!r} to {convert.__name__}"
        ) from None


def failure_reason(exc: ValidationError, fallback: str) -> str:
    """The message a ``parse`` raised, else ``fallback`` for a type mismatch."""
    error = exc.errors()[0].get("ctx", {}).get("error")
    return str(error) if isinstance(error, ValueError) else fallback


@dataclass(frozen=True)
class Extractor:
    """Per-field state for pydantic: the field's extract name and spec.
    The validation context carries the row's warnings and miss reasons."""

    name: str
    spec: ExtractSpec

    py_type: ClassVar[Any] = Any
    default_pattern: ClassVar[re.Pattern[str] | None] = None
    blank_is_null: ClassVar[bool] = True

    def __get_pydantic_core_schema__(
        self, source: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        prepared = core_schema.with_info_before_validator_function(
            self.prepare, handler(source)
        )
        return core_schema.with_info_wrap_validator_function(self.lenient, prepared)

    @property
    def pattern(self) -> re.Pattern[str] | None:
        return self.spec.pattern or self.default_pattern

    def parse(self, matched: Any) -> Any:
        """The typed value; a ``ValueError`` message becomes the warning's reason."""
        return matched

    def prepare(self, raw: Any, info: ValidationInfo) -> Any:
        if raw is None:
            return None
        found = self.picked(raw, info)
        if found is None:
            return None
        if self.blank_is_null and not str(found).strip():
            self.context(info)["reasons"][self.name] = f"blank value {raw!r}"
            return None
        return self.parse(found)

    def picked(self, raw: Any, info: ValidationInfo) -> Any:
        """The pattern's pick, or ``None`` with the miss reason kept."""
        pattern = self.pattern
        if pattern is None:
            return raw
        found = matched(str(raw), pattern)
        if found is None:
            reason = f"no match for pattern {pattern.pattern!r} in {str(raw)!r}"
            self.context(info)["reasons"][self.name] = reason
        return found

    def lenient(
        self,
        raw: Any,
        handler: core_schema.ValidatorFunctionWrapHandler,
        info: ValidationInfo,
    ) -> Any:
        try:
            return handler(raw)
        except ValidationError as exc:
            reason = failure_reason(
                exc, f"could not convert {raw!r} to {self.spec.type}"
            )
            context = self.context(info)
            context["reasons"][self.name] = reason
            context["warnings"].append(
                ExtractWarning(field=self.name, raw=str(raw), reason=reason)
            )
            return None

    @staticmethod
    def context(info: ValidationInfo) -> dict[str, Any]:
        context: dict[str, Any] | None = info.context
        assert context is not None, "typed rows validate with a context"
        return context


@get_extractors().register("str")
class StrExtractor(Extractor):
    blank_is_null = False


@get_extractors().register("int")
class IntExtractor(Extractor):
    py_type: ClassVar[Any] = int
    default_pattern = re.compile(NUMBER_PATTERN)

    def parse(self, matched: Any) -> Any:
        return converted(matched, int)


@get_extractors().register("float")
class FloatExtractor(IntExtractor):
    py_type: ClassVar[Any] = float

    def parse(self, matched: Any) -> Any:
        return converted(matched, float)


@get_extractors().register("date")
class DateExtractor(Extractor):
    py_type: ClassVar[Any] = datetime.date

    def parse(self, matched: Any) -> Any:
        text = str(matched).strip()
        parsed = parsed_date(text, self.spec)
        if parsed is None:
            raise ValueError(f"could not parse {text!r} as a date")
        return parsed
