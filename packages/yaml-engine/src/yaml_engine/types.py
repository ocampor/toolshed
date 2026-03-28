"""Base type definitions for compiled structures."""

import re
from dataclasses import dataclass, field
from typing import Literal

type CompiledParam = re.Pattern[str] | frozenset[str] | list[str] | str | int | float | dict[str, str] | None


@dataclass(frozen=True)
class CompiledCondition[P]:
    field: str
    op: str
    param: P
    source: Literal["record", "context"] = "record"


@dataclass(frozen=True)
class CompiledAction[P]:
    op: str
    param: P


@dataclass(frozen=True)
class CompiledRule:
    conditions: tuple[CompiledCondition[CompiledParam], ...]
    actions: tuple[CompiledAction[CompiledParam], ...]


@dataclass(frozen=True)
class CompiledGroup:
    name: str
    priority: int
    first_match: bool
    rules: tuple[CompiledRule, ...]
    skip_if_set: str | None = None
    extra: dict[str, object] = field(default_factory=dict)
