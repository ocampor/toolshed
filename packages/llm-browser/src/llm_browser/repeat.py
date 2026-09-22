"""What a repeating step loops over, and the block form that sugars it.

One engine: ``repeat:`` on a step is the modifier form, and ``action: repeat``
with ``steps:`` is rewritten into a ``run-flow`` carrying that same modifier
before anything else sees the flow.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from llm_browser.selectors import PlainSelector, Selector


class OnError(enum.StrEnum):
    stop = "stop"
    skip = "skip"


RepeatItem = str | int | float | bool


@dataclass(frozen=True)
class ElementScope:
    root: PlainSelector
    index: int


class Repeat(BaseModel):
    """Run one step once per item of a list, or once per matched element.

    ``over`` names a list param or is the list itself; ``over_selector``
    repeats over what it matches, counted once when the step starts. ``as``
    (the field is ``bind``, because ``as`` is a keyword) names the variable
    each item is bound to for that pass, alongside ``<as>_index``.

    Each pass is its own scope: a ``when:`` is re-evaluated per pass, a
    ``save_as`` inside one is invisible outside it, and a step that needs the
    pass's element addresses it with ``in: <as>``. ``on_error: skip`` keeps the
    run going past a failed pass and leaves a retry hint naming the passes that
    failed — by index for an element repeat, as data for a list param, because
    a rerun renumbers those from zero.
    """

    model_config = ConfigDict(populate_by_name=True)

    over: str | list[RepeatItem] | None = None
    over_selector: Selector | None = None
    bind: str = Field(..., min_length=1, alias="as")
    on_error: OnError = OnError.stop

    @property
    def param(self) -> str | None:
        return self.over if isinstance(self.over, str) else None

    @model_validator(mode="after")
    def _check_source(self) -> Repeat:
        if (self.over is None) == (self.over_selector is None):
            raise ValueError("repeat takes exactly one of `over` or `over_selector`")
        # Binding the item to the list's own name would leave the rest of the
        # step unable to reach either.
        if self.bind == self.param:
            raise ValueError(f"repeat `as` must differ from `over` ({self.over!r})")
        return self


class RepeatBlock(BaseModel):
    """``action: repeat`` with a body — sugar for a repeated inline ``run-flow``."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    action: Literal["repeat"]
    name: str = "unnamed"
    over: str | list[RepeatItem] | None = None
    over_selector: Selector | None = None
    bind: str = Field(..., min_length=1, alias="as")
    on_error: OnError = OnError.stop
    when: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _check_body(self) -> RepeatBlock:
        # A repeat body is flat: nothing in it may open a loop or a sub-flow.
        for step in self.steps:
            if step.get("action") in {"run-flow", "repeat"} or "repeat" in step:
                raise ValueError(
                    f"repeat body step {step.get('name', 'unnamed')!r} may not be "
                    "a `run-flow`, a nested `repeat`, or carry a `repeat:` modifier"
                )
        return self

    def desugared(self) -> dict[str, Any]:
        return {
            "action": "run-flow",
            "name": self.name,
            "when": self.when,
            "repeat": {
                "over": self.over,
                "over_selector": self.over_selector,
                "as": self.bind,
                "on_error": self.on_error,
            },
            "flow": {"steps": self.steps},
        }


def check_scope(step: Any, repeat: Repeat | None) -> None:
    """``in: <as>`` names the element binding of the repeat the step sits in."""
    scope = step.scope
    if scope is None:
        return
    if repeat is None or repeat.over_selector is None:
        raise ValueError(
            f"step {step.name!r} uses `in: {scope}` but is not inside a "
            "repeat over `over_selector`"
        )
    if scope != repeat.bind:
        raise ValueError(
            f"step {step.name!r} uses `in: {scope}` but the repeat "
            f"binds {repeat.bind!r}"
        )
    if getattr(step, "selector", None) is None:
        raise ValueError(f"step {step.name!r} uses `in: {scope}` but names no selector")
