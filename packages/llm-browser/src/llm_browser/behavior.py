"""Humanization config for action handlers (opt-in).

Driver-agnostic timing knobs live here. Playwright-family drivers invoke
`humanized_click` / `humanized_type` directly; non-Playwright drivers
(e.g. nodriver) use their own native humanization and honor only the
timing fields through the pure helpers (`enforce_gap`, `post_pause`).
"""

import random
import time
from typing import Any, Self

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
    click_offset_px: int = 8
    mouse_move_steps: int = 30
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
        """Timing-level humanization only.

        Covers inter-key gaps, click jitter, mouse paths, pre-click pauses,
        and post-action pauses for actions routed through
        ``execute_action(...)``. Does NOT modify runtime JS fingerprints
        (navigator properties, WebGL, canvas, CDP detection) — use the
        ``patchright`` or ``camoufox`` drivers for those. Calls on the raw
        ``Page`` / ``Locator`` returned by ``session.get_page()`` bypass
        this entirely.
        """
        # Never set `seed` — deterministic jitter is what detectors look for.
        return cls()

    def runtime(self) -> BehaviorRuntime:
        return BehaviorRuntime(rng=random.Random(self.seed))


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


def jittered_sleep(jitter: Jitter, rng: random.Random) -> None:
    time.sleep(jitter.sample_seconds(rng))


def humanized_click(
    page: Any,
    element: Any,
    behavior: Behavior,
    runtime: BehaviorRuntime,
) -> None:
    """Click with jittered pre-pause, mouse move, and offset target."""
    jittered_sleep(behavior.pre_click_pause, runtime.rng)
    x, y = _jittered_target(element, behavior, runtime)
    page.mouse.move(x, y, steps=max(1, behavior.mouse_move_steps))
    page.mouse.click(x, y)


def humanized_type(
    page: Any,
    element: Any,
    text: str,
    behavior: Behavior,
    runtime: BehaviorRuntime,
) -> None:
    """Type text char-by-char with jittered per-key delays."""
    if behavior.focus_drift and behavior.mouse_move:
        _drift_mouse_to(page, element, behavior, runtime)
    for ch in text:
        _type_char(element, ch, behavior, runtime)


def _jittered_target(
    element: Any,
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


def _drift_mouse_to(
    page: Any,
    element: Any,
    behavior: Behavior,
    runtime: BehaviorRuntime,
) -> None:
    x, y = _jittered_target(element, behavior, runtime)
    page.mouse.move(x, y, steps=max(1, behavior.mouse_move_steps // 2))


def _type_char(
    element: Any, ch: str, behavior: Behavior, runtime: BehaviorRuntime
) -> None:
    element.type(ch, delay=0)
    jittered_sleep(behavior.type_char_delay, runtime.rng)
    if ch in ".,?!;:\n":
        jittered_sleep(behavior.type_punct_pause, runtime.rng)
