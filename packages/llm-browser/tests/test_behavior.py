"""Tests for the behavior layer (humanization config + runtime helpers)."""

import random
from unittest.mock import MagicMock

import pytest

from llm_browser import behavior as behavior_module
from llm_browser.actions import execute_action
from llm_browser.behavior import (
    MOUSE_APPROACH_PX,
    Behavior,
    Jitter,
    approach_start,
    boundary_pause,
    curve_points,
    enforce_gap,
    forget_mouse,
    humanized_click,
    humanized_type,
    jittered_delta,
    jittered_target,
    mark_action_done,
    post_pause,
)
from llm_browser.models import ClickStep, FillStep, ScrollStep, ThinkStep, TypeStep
from llm_browser.session import BrowserSession


def _locator_with_box(box: dict[str, float] | None = None) -> MagicMock:
    locator = MagicMock()
    locator.count.return_value = 1
    locator.first.bounding_box.return_value = box or {
        "x": 100.0,
        "y": 50.0,
        "width": 200.0,
        "height": 40.0,
    }
    return locator


@pytest.fixture
def session(tmp_path: object) -> BrowserSession:
    s = BrowserSession(state_dir=tmp_path)  # type: ignore[arg-type]
    mock_page = MagicMock()
    mock_page.locator.return_value = _locator_with_box()
    s._page = mock_page
    return s


# --- Jitter ---


def test_jitter_zero_returns_zero() -> None:
    rng = random.Random(0)
    assert Jitter().sample_seconds(rng) == 0.0


def test_jitter_sample_within_bounds() -> None:
    j = Jitter(min_ms=30, max_ms=90)
    rng = random.Random(42)
    for _ in range(10_000):
        delay = j.sample_seconds(rng)
        assert 0.030 <= delay <= 0.090


def test_jitter_rejects_inverted_bounds() -> None:
    with pytest.raises(ValueError, match=">="):
        Jitter(min_ms=100, max_ms=50)


def test_jitter_rejects_negative() -> None:
    with pytest.raises(ValueError, match=">= 0"):
        Jitter(min_ms=-1, max_ms=10)


# --- Presets ---


def test_off_preset_disables_everything() -> None:
    b = Behavior.off()
    assert b.type_char_delay == Jitter()
    assert b.type_punct_pause == Jitter()
    assert b.pre_click_pause == Jitter()
    assert b.post_action_pause == Jitter()
    assert b.mouse_move is False
    assert b.fill_as_type is False
    assert b.focus_drift is False
    assert b.click_offset_ratio == 0.0
    assert b.scroll_delta_jitter == 0.0
    assert b.mouse_move_steps == 0
    assert b.hover_dwell == Jitter()
    assert b.press_hold == Jitter()
    assert b.type_word_pause == Jitter()
    assert b.min_gap_ms == 0


def test_pace_preset_no_mouse() -> None:
    b = Behavior.pace()
    assert b.mouse_move is False
    assert b.focus_drift is False
    assert b.fill_as_type is True
    assert b.type_char_delay.max_ms > 0


def test_human_preset_all_on_no_seed() -> None:
    b = Behavior.human()
    assert b.mouse_move is True
    assert b.focus_drift is True
    assert b.fill_as_type is True
    assert b.seed is None, "human() must not seed — deterministic jitter is a tell"


# --- Runtime determinism (test wiring only, not a property of human()) ---


def test_seeded_runtime_produces_identical_sequences() -> None:
    b = Behavior(seed=7)
    r1 = b.runtime()
    r2 = b.runtime()
    s1 = [b.type_char_delay.sample_seconds(r1.rng) for _ in range(1000)]
    s2 = [b.type_char_delay.sample_seconds(r2.rng) for _ in range(1000)]
    assert s1 == s2


# --- Helpers ---


def test_enforce_gap_sleeps_when_under_min() -> None:
    b = Behavior(min_gap_ms=50)
    r = b.runtime()
    r.last_action_monotonic = 9e9  # in the future -> positive remaining
    with pytest.MonkeyPatch.context() as mp:
        calls: list[float] = []
        mp.setattr("llm_browser.behavior.time.sleep", lambda s: calls.append(s))
        mp.setattr("llm_browser.behavior.time.monotonic", lambda: 9e9)
        enforce_gap(b, r)
        assert calls and calls[0] > 0


def test_enforce_gap_skips_when_disabled() -> None:
    b = Behavior.off()
    r = b.runtime()
    r.last_action_monotonic = 0.0
    with pytest.MonkeyPatch.context() as mp:
        calls: list[float] = []
        mp.setattr("llm_browser.behavior.time.sleep", lambda s: calls.append(s))
        enforce_gap(b, r)
        assert calls == []


def test_post_pause_never_stamps_clock() -> None:
    b = Behavior(min_gap_ms=50)
    r = b.runtime()
    post_pause(b, r)
    assert r.last_action_monotonic is None


def test_mark_action_done_stamps_clock() -> None:
    r = Behavior.off().runtime()
    mark_action_done(r)
    assert r.last_action_monotonic is not None


def test_humanized_type_types_char_by_char() -> None:
    b = Behavior(
        type_char_delay=Jitter(min_ms=1, max_ms=2),
        type_punct_pause=Jitter(),
        focus_drift=False,
    )
    r = b.runtime()
    page = MagicMock()
    element = MagicMock()
    humanized_type(page, element, "hi", b, r)
    assert element.type.call_count == 2
    element.type.assert_any_call("h", delay=0)
    element.type.assert_any_call("i", delay=0)


BOX = {"x": 10.0, "y": 20.0, "width": 100.0, "height": 40.0}


def _element_at(box: dict[str, float] | None = BOX) -> MagicMock:
    element = MagicMock()
    element.bounding_box.return_value = box
    return element


def test_humanized_click_walks_a_curve_and_presses_with_a_gap() -> None:
    b = Behavior(pre_click_pause=Jitter(), mouse_move_steps=12)
    r = b.runtime()
    page = MagicMock()
    humanized_click(page, _element_at(), b, r)
    path = [call.args for call in page.mouse.move.call_args_list]
    assert 6 <= len(path) <= 12
    assert path[-1] == r.mouse_xy
    page.mouse.down.assert_called_once_with()
    page.mouse.up.assert_called_once_with()
    page.mouse.click.assert_not_called()


def test_click_target_spreads_with_the_offset_ratio() -> None:
    """The offset is a fraction of the half-extent, so it scales with the box
    instead of with a pixel count — and never leaves the element."""
    b = Behavior(click_offset_ratio=0.3)
    r = b.runtime()
    targets = [jittered_target(_element_at(), b, r) for _ in range(2000)]
    xs = [x for x, _y in targets]
    ys = [y for _x, y in targets]
    assert 60.0 - 15.0 <= min(xs) and max(xs) <= 60.0 + 15.0
    assert 40.0 - 6.0 <= min(ys) and max(ys) <= 40.0 + 6.0
    assert max(xs) - min(xs) > 15.0


def test_a_curve_bows_off_the_straight_line() -> None:
    points = curve_points((0.0, 0.0), (100.0, 0.0), 10, random.Random(3))
    assert points[-1] == (100.0, 0.0)
    assert max(abs(y) for _x, y in points) > 1.0


def test_a_curve_is_monotonic_towards_its_end() -> None:
    """Bézier control points never drag the path past its endpoint."""
    points = curve_points((0.0, 0.0), (100.0, 0.0), 20, random.Random(11))
    assert [x for x, _y in points] == sorted(x for x, _y in points)


def test_word_boundary_pauses_sometimes_and_punctuation_always() -> None:
    b = Behavior(type_word_pause_chance=0.5)
    rng = random.Random(0)
    assert boundary_pause(".", b, rng) == b.type_punct_pause
    assert boundary_pause("a", b, rng) is None
    spaces = [boundary_pause(" ", b, rng) for _ in range(500)]
    assert 0 < sum(pause is not None for pause in spaces) < 500
    assert set(spaces) == {None, b.type_word_pause}


def test_word_boundary_pause_is_shorter_than_the_punctuation_one() -> None:
    b = Behavior()
    assert b.type_word_pause.max_ms < b.type_punct_pause.max_ms


def test_scroll_delta_jitter_stays_within_its_spread() -> None:
    b = Behavior(scroll_delta_jitter=0.2)
    rng = random.Random(5)
    deltas = [jittered_delta(600, b, rng) for _ in range(1000)]
    assert all(480 <= d <= 720 for d in deltas)
    assert len(set(deltas)) > 1


def test_scroll_delta_is_exact_when_the_behavior_is_off() -> None:
    b = Behavior.off()
    rng = random.Random(5)
    assert {jittered_delta(600, b, rng) for _ in range(50)} == {600}


def test_humanized_click_raises_when_no_bbox() -> None:
    b = Behavior()
    r = b.runtime()
    page = MagicMock()
    with pytest.raises(RuntimeError, match="bounding box"):
        humanized_click(page, _element_at(None), b, r)
    page.mouse.move.assert_not_called()


# --- Regression: default session preserves existing semantics ---


def test_default_session_fill_still_calls_fill(session: BrowserSession) -> None:
    step = FillStep(name="s", action="fill", selector="#input", value="hello")
    execute_action(session, step)
    locator = session._page.locator.return_value  # type: ignore[union-attr]
    locator.first.fill.assert_called_once_with("hello")
    locator.first.type.assert_not_called()


def test_default_session_scroll_uses_the_exact_delta(session: BrowserSession) -> None:
    step = ScrollStep(name="s", action="scroll", delta=600, times=1)
    execute_action(session, step)
    session._page.mouse.wheel.assert_called_once_with(0, 600)  # type: ignore[union-attr]


def test_default_session_click_uses_plain_click(session: BrowserSession) -> None:
    step = ClickStep(name="s", action="click", selector="#btn")
    execute_action(session, step)
    locator = session._page.locator.return_value  # type: ignore[union-attr]
    locator.first.click.assert_called_once()
    session._page.mouse.move.assert_not_called()  # type: ignore[union-attr]


def test_default_session_type_respects_delay(session: BrowserSession) -> None:
    step = TypeStep(name="s", action="type", selector="#q", value="ab", delay=25)
    execute_action(session, step)
    locator = session._page.locator.return_value  # type: ignore[union-attr]
    locator.first.type.assert_called_once_with("ab", delay=25)


# --- Behavior.human() changes the dispatch path ---


def test_human_session_fill_routes_to_type(tmp_path: object) -> None:
    s = BrowserSession(state_dir=tmp_path, behavior=Behavior.human())  # type: ignore[arg-type]
    mock_page = MagicMock()
    mock_page.locator.return_value = _locator_with_box()
    s._page = mock_page
    step = FillStep(name="s", action="fill", selector="#input", value="hi")
    execute_action(s, step)
    locator = s._page.locator.return_value
    locator.first.fill.assert_not_called()
    assert locator.first.type.call_count == 2


def test_human_session_click_uses_mouse(tmp_path: object) -> None:
    s = BrowserSession(state_dir=tmp_path, behavior=Behavior.human())  # type: ignore[arg-type]
    mock_page = MagicMock()
    mock_page.locator.return_value = _locator_with_box()
    s._page = mock_page
    step = ClickStep(name="s", action="click", selector="#btn")
    execute_action(s, step)
    assert mock_page.mouse.move.called
    assert mock_page.mouse.down.called
    assert mock_page.mouse.up.called


def test_dispatch_click_bypasses_humanization(tmp_path: object) -> None:
    s = BrowserSession(state_dir=tmp_path, behavior=Behavior.human())  # type: ignore[arg-type]
    mock_page = MagicMock()
    mock_page.locator.return_value = _locator_with_box()
    s._page = mock_page
    step = ClickStep(name="s", action="click", selector="#btn", dispatch=True)
    execute_action(s, step)
    locator = s._page.locator.return_value
    locator.first.dispatch_event.assert_called_once_with("click")
    mock_page.mouse.move.assert_not_called()


# --- think action ---


def test_think_sleeps_within_bounds(session: BrowserSession) -> None:
    step = ThinkStep(name="s", action="think", min_ms=10, max_ms=20)
    with pytest.MonkeyPatch.context() as mp:
        calls: list[float] = []
        mp.setattr("llm_browser.actions.time.sleep", lambda s: calls.append(s))
        execute_action(session, step)
    think_sleeps = [c for c in calls if c > 0]
    assert len(think_sleeps) == 1
    assert 0.010 <= think_sleeps[0] <= 0.020


def test_think_rejects_inverted_bounds(session: BrowserSession) -> None:
    """``min_ms > max_ms`` triggers Pydantic validation inside Jitter, which
    bubbles to ``execute_action`` and is returned as ``ErrorResult``."""
    from llm_browser.actions import ErrorResult

    step = ThinkStep(name="s", action="think", min_ms=100, max_ms=50)
    result = execute_action(session, step)
    assert isinstance(result, ErrorResult)
    assert "max_ms" in result.message


# --- The pointer between actions ---


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr(behavior_module.time, "sleep", recorded.append)
    return recorded


def _page_with_viewport(width: float, height: float) -> MagicMock:
    page = MagicMock()
    page.viewport_size = {"width": width, "height": height}
    return page


def test_a_mouse_path_stays_inside_the_viewport(no_sleep: list[float]) -> None:
    """The bow is a fraction of the distance, so a long approach to an element
    at the edge swings off-screen — where no real pointer can be."""
    corner = {"x": 0.0, "y": 0.0, "width": 40.0, "height": 20.0}
    for seed in range(20):
        b = Behavior(pre_click_pause=Jitter(), mouse_move_steps=8, seed=seed)
        r = b.runtime()
        r.mouse_xy = (0.0, 500.0)
        page = _page_with_viewport(800.0, 600.0)
        humanized_click(page, _element_at(corner), b, r)
        path = [call.args for call in page.mouse.move.call_args_list]
        assert all(0.0 <= x <= 800.0 and 0.0 <= y <= 600.0 for x, y in path), path


def test_an_unknown_pointer_approaches_from_its_own_neighbourhood() -> None:
    target = (400.0, 300.0)
    starts = [approach_start(target, random.Random(seed)) for seed in range(50)]
    assert all(
        abs(x - target[0]) <= MOUSE_APPROACH_PX
        and abs(y - target[1]) <= MOUSE_APPROACH_PX
        for x, y in starts
    )
    assert len(set(starts)) == len(starts)


def test_a_forgotten_pointer_does_not_teleport_from_the_origin(
    no_sleep: list[float],
) -> None:
    b = Behavior(pre_click_pause=Jitter(), mouse_move_steps=8, seed=3)
    r = b.runtime()
    forget_mouse(r)
    page = _page_with_viewport(1000.0, 800.0)
    humanized_click(
        page, _element_at({"x": 600.0, "y": 400.0, "width": 40.0, "height": 20.0}), b, r
    )
    first = page.mouse.move.call_args_list[0].args
    assert first[0] > MOUSE_APPROACH_PX and first[1] > MOUSE_APPROACH_PX


def test_the_path_is_paced_point_by_point(no_sleep: list[float]) -> None:
    """A trail with a shape but no speed still reads as synthetic."""
    b = Behavior(
        pre_click_pause=Jitter(),
        hover_dwell=Jitter(),
        press_hold=Jitter(),
        mouse_move_steps=10,
        seed=5,
    )
    r = b.runtime()
    page = _page_with_viewport(800.0, 600.0)
    humanized_click(page, _element_at(), b, r)
    moves = page.mouse.move.call_count
    gaps = [slept for slept in no_sleep if slept > 0.0]
    assert len(gaps) == moves
    assert len(set(gaps)) > 1
