"""Humanization config for action handlers (opt-in)."""

import random
import time
from typing import Self

from patchright.sync_api import Locator, Page
from pydantic import BaseModel, ConfigDict, model_validator


class Jitter(BaseModel):
    model_config = ConfigDict(frozen=True)

    min_ms: int = 0
    max_ms: int = 0

    @model_validator(mode="after")
    def _check_bounds(self) -> Self:
        if self.max_ms < self.min_ms:
            raise ValueError("Jitter.max_ms must be >= min_ms")
        if self.min_ms < 0:
            raise ValueError("Jitter.min_ms must be >= 0")
        return self

    def sample_seconds(self, rng: random.Random) -> float:
        return rng.uniform(self.min_ms, self.max_ms) / 1000.0


class BehaviorRuntime:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.last_action_monotonic: float | None = None


class Behavior(BaseModel):
    model_config = ConfigDict(frozen=True)

    type_char_delay: Jitter = Jitter(min_ms=30, max_ms=90)
    type_punct_pause: Jitter = Jitter(min_ms=120, max_ms=300)
    pre_click_pause: Jitter = Jitter(min_ms=120, max_ms=400)
    post_action_pause: Jitter = Jitter(min_ms=200, max_ms=800)
    click_offset_px: int = 3
    mouse_move_steps: int = 12
    mouse_move: bool = True
    fill_as_type: bool = True
    focus_drift: bool = True
    min_gap_ms: int = 0
    seed: int | None = None

    @classmethod
    def off(cls) -> Self:
        return BEHAVIOR_OFF  # type: ignore[return-value]

    @classmethod
    def pace(cls) -> Self:
        return cls(mouse_move=False, focus_drift=False)

    @classmethod
    def human(cls) -> Self:
        # Never set `seed` — deterministic jitter is what detectors look for.
        return cls()

    def runtime(self) -> BehaviorRuntime:
        return BehaviorRuntime(rng=random.Random(self.seed))


PUNCTUATION = frozenset(".,?!;:\n")
ZERO_JITTER = Jitter()
BEHAVIOR_OFF = Behavior(
    type_char_delay=ZERO_JITTER,
    type_punct_pause=ZERO_JITTER,
    pre_click_pause=ZERO_JITTER,
    post_action_pause=ZERO_JITTER,
    click_offset_px=0,
    mouse_move_steps=0,
    mouse_move=False,
    fill_as_type=False,
    focus_drift=False,
    min_gap_ms=0,
)


def enforce_gap(behavior: Behavior, runtime: BehaviorRuntime) -> None:
    if behavior.min_gap_ms <= 0 or runtime.last_action_monotonic is None:
        return
    remaining = behavior.min_gap_ms / 1000.0 - (
        time.monotonic() - runtime.last_action_monotonic
    )
    if remaining > 0:
        time.sleep(remaining)


def post_pause(behavior: Behavior, runtime: BehaviorRuntime) -> None:
    jittered_sleep(behavior.post_action_pause, runtime.rng)


def mark_action_done(runtime: BehaviorRuntime) -> None:
    runtime.last_action_monotonic = time.monotonic()


def humanized_type(
    page: Page,
    element: Locator,
    text: str,
    behavior: Behavior,
    runtime: BehaviorRuntime,
) -> None:
    if behavior.focus_drift and behavior.mouse_move:
        drift_mouse_to(page, element, behavior, runtime)
    for ch in text:
        type_char(element, ch, behavior, runtime)


def humanized_click(
    page: Page,
    element: Locator,
    behavior: Behavior,
    runtime: BehaviorRuntime,
) -> None:
    jittered_sleep(behavior.pre_click_pause, runtime.rng)
    x, y = jittered_target(element, behavior, runtime)
    page.mouse.move(x, y, steps=max(1, behavior.mouse_move_steps))
    page.mouse.click(x, y)


def jittered_sleep(jitter: Jitter, rng: random.Random) -> None:
    time.sleep(jitter.sample_seconds(rng))


def type_char(
    element: Locator, ch: str, behavior: Behavior, runtime: BehaviorRuntime
) -> None:
    element.type(ch, delay=0)
    jittered_sleep(behavior.type_char_delay, runtime.rng)
    if ch in PUNCTUATION:
        jittered_sleep(behavior.type_punct_pause, runtime.rng)


def drift_mouse_to(
    page: Page,
    element: Locator,
    behavior: Behavior,
    runtime: BehaviorRuntime,
) -> None:
    # Closes the idle-cursor tell during jittered typing.
    x, y = jittered_target(element, behavior, runtime)
    page.mouse.move(x, y, steps=max(1, behavior.mouse_move_steps // 2))


def jittered_target(
    element: Locator,
    behavior: Behavior,
    runtime: BehaviorRuntime,
) -> tuple[float, float]:
    box = element.bounding_box()
    if box is None:
        raise RuntimeError("element has no bounding box (detached or not rendered)")
    cx = box["x"] + box["width"] / 2.0
    cy = box["y"] + box["height"] / 2.0
    offset = behavior.click_offset_px
    return (
        cx + runtime.rng.uniform(-offset, offset),
        cy + runtime.rng.uniform(-offset, offset),
    )
