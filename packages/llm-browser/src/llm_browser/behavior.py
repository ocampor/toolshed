"""Humanization config for browser input (opt-in).

Driver-agnostic timing knobs live here. `paced` is the entry point every
caller uses: it brackets one interaction with its inter-action gap and its
post-action pause (`enforce_gap` / `post_pause` are its pieces).
Playwright-family drivers invoke `humanized_click` / `humanized_type`
directly; non-Playwright drivers (e.g. nodriver) use their own native
humanization and honor only the timing fields.
"""

import random
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

PUNCTUATION = ".,?!;:\n"

# How far off the straight line the Bézier control point may sit, as a
# fraction of the travelled distance.
MOUSE_BOW_RATIO = 0.2


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
        self.pacing = False
        # Where the pointer was left. A fresh page starts it at the origin.
        self.mouse_xy: tuple[float, float] = (0.0, 0.0)


class Behavior(BaseModel):
    model_config = ConfigDict(frozen=True)

    type_char_delay: Jitter = Jitter(min_ms=30, max_ms=90)
    type_punct_pause: Jitter = Jitter(min_ms=120, max_ms=300)
    type_word_pause: Jitter = Jitter(min_ms=60, max_ms=180)
    type_word_pause_chance: float = Field(default=0.15, ge=0.0, le=1.0)
    pre_click_pause: Jitter = Jitter(min_ms=120, max_ms=400)
    hover_dwell: Jitter = Jitter(min_ms=80, max_ms=300)
    press_hold: Jitter = Jitter(min_ms=60, max_ms=140)
    post_action_pause: Jitter = Jitter(min_ms=200, max_ms=800)
    click_offset_ratio: float = Field(default=0.3, ge=0.0, le=1.0)
    scroll_delta_jitter: float = Field(default=0.15, ge=0.0, le=1.0)
    mouse_move_steps: int = 20
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

        Covers inter-key gaps, click jitter, mouse paths, pre-click pauses
        and post-action pauses for every ``BrowserSession`` input method, and
        so for the flow steps built on them. Does NOT modify runtime JS
        fingerprints (navigator properties, WebGL, canvas, CDP detection) —
        use the ``patchright`` or ``camoufox`` drivers for those. Calls on a
        raw driver locator or page (``session.find``, ``session.get_page``)
        bypass this entirely.
        """
        # Never set `seed` — deterministic jitter is what detectors look for.
        return cls()

    def runtime(self) -> BehaviorRuntime:
        return BehaviorRuntime(rng=random.Random(self.seed))


ZERO_JITTER = Jitter()
BEHAVIOR_OFF = Behavior(
    type_char_delay=ZERO_JITTER,
    type_punct_pause=ZERO_JITTER,
    type_word_pause=ZERO_JITTER,
    type_word_pause_chance=0.0,
    pre_click_pause=ZERO_JITTER,
    hover_dwell=ZERO_JITTER,
    press_hold=ZERO_JITTER,
    post_action_pause=ZERO_JITTER,
    click_offset_ratio=0.0,
    scroll_delta_jitter=0.0,
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


@contextmanager
def paced(behavior: Behavior, runtime: BehaviorRuntime) -> Iterator[None]:
    """Bracket one action with its gap and post-action pause.

    A raise skips the post-pause, so a failed step does not sit out a pause it
    never earned. Nested scopes defer to the outermost one: a session input
    method called from an action handler must not pause twice.
    """
    if runtime.pacing:
        yield
        return
    runtime.pacing = True
    try:
        enforce_gap(behavior, runtime)
        yield
        post_pause(behavior, runtime)
        mark_action_done(runtime)
    finally:
        runtime.pacing = False


def jittered_sleep(jitter: Jitter, rng: random.Random) -> None:
    time.sleep(jitter.sample_seconds(rng))


def jittered_delta(delta: int, behavior: Behavior, rng: random.Random) -> int:
    """Wheel ticks of identical size are a tell; this is the fraction one may
    stray from the delta the step asked for."""
    spread = behavior.scroll_delta_jitter
    return round(delta * (1.0 + rng.uniform(-spread, spread)))


def humanized_click(
    page: Any,
    element: Any,
    behavior: Behavior,
    runtime: BehaviorRuntime,
) -> None:
    """Approach on a curve, dwell, then press and release with a gap.

    Trail shape, hover dwell, offset entropy and press duration are the four
    things a behavioral score reads off a pointer, so no part of this is a
    constant.
    """
    jittered_sleep(behavior.pre_click_pause, runtime.rng)
    target = jittered_target(element, behavior, runtime)
    move_mouse_to(page, target, runtime, path_steps(behavior, runtime.rng))
    jittered_sleep(behavior.hover_dwell, runtime.rng)
    page.mouse.down()
    jittered_sleep(behavior.press_hold, runtime.rng)
    page.mouse.up()


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


def jittered_target(
    element: Any,
    behavior: Behavior,
    runtime: BehaviorRuntime,
) -> tuple[float, float]:
    """A point ``click_offset_ratio`` of the way from the centre to an edge,
    so the spread scales with the element instead of with a pixel count."""
    box = element.bounding_box()
    if box is None:
        raise RuntimeError("element has no bounding box (detached or not rendered)")
    ratio = behavior.click_offset_ratio
    half_width = box["width"] / 2.0
    half_height = box["height"] / 2.0
    return (
        box["x"] + half_width * (1.0 + runtime.rng.uniform(-ratio, ratio)),
        box["y"] + half_height * (1.0 + runtime.rng.uniform(-ratio, ratio)),
    )


def path_steps(behavior: Behavior, rng: random.Random) -> int:
    """Half to all of ``mouse_move_steps`` points on the way: the number of
    samples varies as much as the path between them does."""
    top = max(1, behavior.mouse_move_steps)
    return rng.randint(max(1, top // 2), top)


def move_mouse_to(
    page: Any,
    target: tuple[float, float],
    runtime: BehaviorRuntime,
    steps: int,
) -> None:
    for x, y in curve_points(runtime.mouse_xy, target, steps, runtime.rng):
        page.mouse.move(x, y)
    runtime.mouse_xy = target


def curve_points(
    start: tuple[float, float],
    end: tuple[float, float],
    steps: int,
    rng: random.Random,
) -> list[tuple[float, float]]:
    """Quadratic Bézier from ``start`` to ``end``, ending exactly on ``end``.

    A hand's path bows; a straight trail at a constant speed is the tell.
    """
    control = bowed_control(start, end, rng)
    return [bezier_point(start, control, end, i / steps) for i in range(1, steps + 1)]


def bowed_control(
    start: tuple[float, float], end: tuple[float, float], rng: random.Random
) -> tuple[float, float]:
    """Midpoint pushed along the perpendicular, either way, by up to
    ``MOUSE_BOW_RATIO`` of the distance."""
    (x0, y0), (x1, y1) = start, end
    bow = rng.uniform(-MOUSE_BOW_RATIO, MOUSE_BOW_RATIO)
    return ((x0 + x1) / 2.0 - (y1 - y0) * bow, (y0 + y1) / 2.0 + (x1 - x0) * bow)


def bezier_point(
    start: tuple[float, float],
    control: tuple[float, float],
    end: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    rest = 1.0 - t
    weights = (rest * rest, 2.0 * rest * t, t * t)
    return (
        weights[0] * start[0] + weights[1] * control[0] + weights[2] * end[0],
        weights[0] * start[1] + weights[1] * control[1] + weights[2] * end[1],
    )


def boundary_pause(ch: str, behavior: Behavior, rng: random.Random) -> Jitter | None:
    """The gap a reader hears: every sentence mark, and some word breaks."""
    if ch in PUNCTUATION:
        return behavior.type_punct_pause
    if ch == " " and rng.random() < behavior.type_word_pause_chance:
        return behavior.type_word_pause
    return None


def _drift_mouse_to(
    page: Any,
    element: Any,
    behavior: Behavior,
    runtime: BehaviorRuntime,
) -> None:
    target = jittered_target(element, behavior, runtime)
    move_mouse_to(page, target, runtime, max(1, path_steps(behavior, runtime.rng) // 2))


def _type_char(
    element: Any, ch: str, behavior: Behavior, runtime: BehaviorRuntime
) -> None:
    element.type(ch, delay=0)
    jittered_sleep(behavior.type_char_delay, runtime.rng)
    pause = boundary_pause(ch, behavior, runtime.rng)
    if pause is not None:
        jittered_sleep(pause, runtime.rng)
