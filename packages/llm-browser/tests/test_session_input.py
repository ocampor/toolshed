"""The session's input methods: resolve, pace, pick the driver primitive."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from llm_browser import behavior as behavior_module
from llm_browser.actions import execute_action
from llm_browser.behavior import Behavior, Jitter
from llm_browser.behavior_config import CamoufoxBehaviorConfig
from llm_browser.models import ClickStep
from llm_browser.results import HitTarget
from llm_browser.session_input import behavior_for, effective_behavior
from llm_browser.session import BrowserSession

PACE_MS = 40
PRE_CLICK_MS = 25
PACED = Behavior(
    post_action_pause=Jitter(min_ms=PACE_MS, max_ms=PACE_MS),
    mouse_move=False,
    fill_as_type=False,
    type_char_delay=Jitter(),
    pre_click_pause=Jitter(),
)


@pytest.fixture
def session(tmp_path: Path) -> BrowserSession:
    s = BrowserSession(state_dir=tmp_path)
    s._page = MagicMock()
    s.driver = MagicMock()
    s.driver.count.return_value = 1
    s.driver.is_visible.return_value = True
    s.driver.first.return_value = "element"
    # In view, and the pointer on the target: what the two scripts a humanized
    # click runs answer for a test that is about something else.
    s.driver.evaluate.return_value = {
        "gap": 0,
        "centre": [400.0, 300.0],
        "target": True,
        "hit": None,
    }
    return s


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr(behavior_module.time, "sleep", recorded.append)
    return recorded


def driver(session: BrowserSession) -> Any:
    return session.driver


# --- routing to driver primitives ---


def test_click_uses_the_plain_primitive(session: BrowserSession) -> None:
    session.click("#btn")
    driver(session).click.assert_called_once_with("element")
    driver(session).dispatch_event.assert_not_called()


def test_click_dispatch_is_opt_in(session: BrowserSession) -> None:
    session.click("#btn", dispatch=True)
    driver(session).dispatch_event.assert_called_once_with("element", "click")
    driver(session).click.assert_not_called()


def test_click_humanizes_when_the_behavior_moves_the_mouse(
    session: BrowserSession,
) -> None:
    session.behavior = Behavior.human()
    session.click("#btn")
    driver(session).humanized_click.assert_called_once()
    driver(session).click.assert_not_called()


def test_click_humanize_true_overrides_a_session_that_is_off(
    session: BrowserSession,
) -> None:
    session.click("#btn", humanize=True)
    driver(session).humanized_click.assert_called_once()
    driver(session).click.assert_not_called()


def test_click_humanize_false_overrides_a_human_session(
    session: BrowserSession,
) -> None:
    session.behavior = Behavior.human()
    session.click("#btn", humanize=False)
    driver(session).click.assert_called_once_with("element")
    driver(session).humanized_click.assert_not_called()


def test_click_humanize_none_follows_the_session(session: BrowserSession) -> None:
    session.click("#btn", humanize=None)
    driver(session).click.assert_called_once_with("element")


def test_type_humanize_true_overrides_a_session_that_is_off(
    session: BrowserSession,
) -> None:
    session.type("#search", "query", humanize=True)
    driver(session).humanized_type.assert_called_once()
    driver(session).type.assert_not_called()


def test_type_humanize_false_overrides_a_human_session(
    session: BrowserSession,
) -> None:
    session.behavior = Behavior.human()
    session.type("#search", "query", humanize=False)
    driver(session).type.assert_called_once_with("element", "query", delay_ms=0)
    driver(session).humanized_type.assert_not_called()


def test_a_jitter_delay_types_humanized_with_that_jitter(
    session: BrowserSession,
) -> None:
    """The per-call jitter replaces the behaviour's own key delay, so an off
    session still types at the cadence the step asked for."""
    delay = Jitter(min_ms=30, max_ms=90)
    session.type("#search", "query", delay_ms=delay)
    driver(session).type.assert_not_called()
    _page, _element, _value, behavior = driver(session).humanized_type.call_args.args
    assert behavior.type_char_delay == delay


def test_fill_uses_the_plain_primitive_when_fill_as_type_is_off(
    session: BrowserSession,
) -> None:
    session.fill("#input", "hello")
    driver(session).fill.assert_called_once_with("element", "hello")


def test_fill_types_when_fill_as_type_is_on(session: BrowserSession) -> None:
    session.behavior = Behavior.pace()
    session.fill("#input", "hello")
    driver(session).humanized_type.assert_called_once()
    driver(session).fill.assert_not_called()


def test_fill_humanize_true_types_on_a_session_that_is_off(
    session: BrowserSession,
) -> None:
    session.fill("#input", "hello", humanize=True)
    driver(session).humanized_type.assert_called_once()
    driver(session).fill.assert_not_called()


def test_fill_humanize_false_sets_the_value_on_a_human_session(
    session: BrowserSession,
) -> None:
    session.behavior = Behavior.human()
    session.fill("#input", "hello", humanize=False)
    driver(session).fill.assert_called_once_with("element", "hello")
    driver(session).humanized_type.assert_not_called()


def test_fill_humanize_true_types_at_the_behaviors_cadence(
    session: BrowserSession,
) -> None:
    """The forced fill types on the humanized cadence, not at zero delay."""
    session.fill("#input", "hello", humanize=True)
    _page, _element, _value, behavior = driver(session).humanized_type.call_args.args
    assert behavior.type_char_delay == Behavior.human().type_char_delay


def test_type_with_an_explicit_delay_beats_the_behavior(
    session: BrowserSession,
) -> None:
    session.behavior = Behavior.human()
    session.type("#search", "query", delay_ms=50)
    driver(session).type.assert_called_once_with("element", "query", delay_ms=50)
    driver(session).humanized_type.assert_not_called()


def test_type_humanizes_when_the_behavior_has_a_key_delay(
    session: BrowserSession,
) -> None:
    session.behavior = Behavior.human()
    session.type("#search", "query")
    driver(session).humanized_type.assert_called_once()


def test_press_without_a_selector_goes_to_the_focused_element(
    session: BrowserSession,
) -> None:
    session.press(None, "Enter")
    driver(session).press_focused.assert_called_once_with(session._page, "Enter")
    driver(session).press.assert_not_called()
    driver(session).resolve.assert_not_called()


def test_press_with_a_selector_resolves_it(session: BrowserSession) -> None:
    session.press("#field", "Enter")
    driver(session).press.assert_called_once_with("element", "Enter")
    driver(session).press_focused.assert_not_called()


def test_select_option(session: BrowserSession) -> None:
    driver(session).evaluate.return_value = "SELECT"
    session.select_option("#dropdown", "opt2")
    driver(session).select_option.assert_called_once_with("element", "opt2")


def test_select_on_a_non_select_is_a_value_error(session: BrowserSession) -> None:
    """A `ValueError` is what `execute_action` turns into an `ErrorResult`;
    the driver's own exception would abort the flow instead."""
    driver(session).evaluate.return_value = "DIV"
    with pytest.raises(
        ValueError, match=r"select needs a <select>; #dropdown is a <div>"
    ):
        session.select_option("#dropdown", "opt2")
    driver(session).select_option.assert_not_called()


def test_set_checked(session: BrowserSession) -> None:
    session.set_checked("#cb", False)
    driver(session).set_checked.assert_called_once_with("element", False)


# --- pacing ---


def test_input_pauses_before_the_action_by_the_min_gap(
    session: BrowserSession, sleeps: list[float]
) -> None:
    """The gap is memoryless: every action pays it, idle or not."""
    session.behavior = PACED.model_copy(update={"min_gap_ms": 100})
    session.click("#btn")
    session.click("#btn")
    gaps = [slept for slept in sleeps if slept != PACE_MS / 1000.0]
    assert len(gaps) == 2
    assert all(0.08 <= gap <= 0.12 for gap in gaps)


def test_input_pauses_after_the_action(
    session: BrowserSession, sleeps: list[float]
) -> None:
    session.behavior = PACED
    session.click("#btn")
    assert sleeps == [PACE_MS / 1000.0]


def test_press_pauses_before_the_key_when_the_behavior_moves_the_mouse(
    session: BrowserSession, sleeps: list[float]
) -> None:
    """A humanized click pauses inside ``humanized_click``; a press has no
    such call to hide behind, so ``press`` owns the pre-click pause itself."""
    session.behavior = PACED.model_copy(
        update={
            "mouse_move": True,
            "pre_click_pause": Jitter(min_ms=PRE_CLICK_MS, max_ms=PRE_CLICK_MS),
        }
    )
    session.press("#field", "Enter")
    assert sleeps == [PRE_CLICK_MS / 1000.0, PACE_MS / 1000.0]


def test_press_skips_the_pre_click_pause_when_the_mouse_stays_put(
    session: BrowserSession, sleeps: list[float]
) -> None:
    """Same non-zero ``pre_click_pause`` as above; only ``mouse_move`` differs."""
    session.behavior = PACED.model_copy(
        update={"pre_click_pause": Jitter(min_ms=PRE_CLICK_MS, max_ms=PRE_CLICK_MS)}
    )
    session.press("#field", "Enter")
    assert sleeps == [PACE_MS / 1000.0]


def test_a_failed_input_skips_the_post_pause(
    session: BrowserSession, sleeps: list[float]
) -> None:
    session.behavior = PACED
    session.driver.click.side_effect = TimeoutError("gone")
    with pytest.raises(TimeoutError):
        session.click("#btn")
    assert sleeps == []


def test_an_action_paces_once_not_twice(
    session: BrowserSession, sleeps: list[float]
) -> None:
    """``execute_action`` opens the pacing scope; the session method it calls
    must defer to it rather than pause a second time."""
    session.behavior = PACED
    execute_action(session, ClickStep(name="s", action="click", selector="#btn"))
    assert sleeps == [PACE_MS / 1000.0]


# --- the session's other click paths ---


def test_pick_clicks_the_way_a_click_step_does(session: BrowserSession) -> None:
    session.behavior = Behavior.human()
    session.driver.text_content.return_value = "Banana"
    session.driver.count.return_value = 2
    session.pick(".option", "Banana")
    driver(session).humanized_click.assert_called_once()
    driver(session).click.assert_not_called()


def test_download_arms_the_trigger_with_the_same_click(
    session: BrowserSession,
) -> None:
    session.behavior = Behavior.human()
    session.download_file("#dl")
    _page, trigger, _timeout = driver(session).download_bytes.call_args.args
    trigger()
    driver(session).humanized_click.assert_called_once()
    driver(session).click.assert_not_called()


# --- what `humanize` switches, and what it leaves alone ---

RATE_LIMITED = Behavior(min_gap_ms=2_000, mouse_move=False, type_char_delay=Jitter())


def test_humanize_true_switches_the_knobs_and_keeps_the_rate_limit(
    session: BrowserSession,
) -> None:
    """`humanize` is a humanization flag, not a fresh config: dropping the
    session's `min_gap_ms` is the one loss that can get a run blocked."""
    session.behavior = RATE_LIMITED
    forced = behavior_for(session.behavior, True)
    assert forced.mouse_move is True
    assert forced.type_char_delay == Behavior.human().type_char_delay
    assert forced.min_gap_ms == 2_000


def test_humanize_false_switches_the_knobs_off_and_keeps_the_rate_limit(
    session: BrowserSession,
) -> None:
    session.behavior = Behavior(min_gap_ms=2_000)
    plain = behavior_for(session.behavior, False)
    assert plain.mouse_move is False
    assert plain.fill_as_type is False
    assert plain.type_char_delay == Jitter()
    assert plain.min_gap_ms == 2_000


def test_humanize_true_honours_a_drivers_own_mouse_humanization(
    session: BrowserSession,
) -> None:
    """Camoufox's native Bézier owns the pointer; stacking ours on top would
    run N native curves for one click."""
    session.behavior = CamoufoxBehaviorConfig(
        driver="camoufox", type_char_delay=Jitter()
    )
    forced = effective_behavior(session, True)
    assert forced.mouse_move is False
    assert forced.focus_drift is False
    assert forced.type_char_delay == Behavior.human().type_char_delay


CAMOUFOX = CamoufoxBehaviorConfig(driver="camoufox")


def test_an_explicit_behavior_honours_a_drivers_own_mouse_humanization(
    session: BrowserSession, sleeps: list[float]
) -> None:
    """Opt-outs are applied last, to a hand-written `Behavior` as much as to
    `humanize: true` — `--behavior human` on camoufox must not stack our
    Bézier on the native one."""
    session.behavior = CAMOUFOX
    session.click("#btn", behavior=Behavior.human())
    driver(session).click.assert_called_once_with("element")
    driver(session).humanized_click.assert_not_called()


def test_a_run_level_behavior_honours_a_drivers_own_mouse_humanization(
    session: BrowserSession, sleeps: list[float]
) -> None:
    session.behavior = CAMOUFOX
    step = ClickStep(name="c", action="click", selector="#btn")
    execute_action(session, step, Behavior.human())
    driver(session).click.assert_called_once_with("element")
    driver(session).humanized_click.assert_not_called()


def test_an_explicit_behavior_keeps_the_knobs_the_driver_does_not_own(
    session: BrowserSession,
) -> None:
    """The opt-out is one knob, not a veto on the whole behaviour."""
    session.behavior = CAMOUFOX
    resolved = effective_behavior(session, behavior=Behavior.human())
    assert resolved.mouse_move is False
    assert resolved.focus_drift is False
    assert resolved.type_char_delay == Behavior.human().type_char_delay


def test_a_session_that_set_the_knob_itself_overrules_the_driver(
    session: BrowserSession,
) -> None:
    """The opt-out is the driver's default, not a lock: a config that asks for
    our mouse path on camoufox gets it."""
    session.behavior = CamoufoxBehaviorConfig(driver="camoufox", mouse_move=True)
    assert effective_behavior(session, behavior=Behavior.human()).mouse_move is True
    assert effective_behavior(session, behavior=Behavior.off()).mouse_move is False


def test_humanize_false_still_jitters_an_explicit_delay_pair(
    session: BrowserSession,
) -> None:
    """`humanize: false` drops the mouse path and the humanized pacing; a
    `[min, max]` the caller wrote is a cadence they asked for, so it stays."""
    session.behavior = Behavior.human()
    delay = Jitter(min_ms=40, max_ms=80)
    session.type("#search", "query", delay_ms=delay, humanize=False)
    driver(session).type.assert_not_called()
    _page, _element, _value, behavior = driver(session).humanized_type.call_args.args
    assert behavior.type_char_delay == delay
    assert behavior.mouse_move is False


def test_humanize_true_leaves_a_tuned_knob_alone(session: BrowserSession) -> None:
    """A key delay someone chose is already humanized the way they meant it;
    `humanize: true` turns humanization on, it does not restore defaults."""
    tuned = Jitter(min_ms=200, max_ms=400)
    session.behavior = Behavior(
        type_char_delay=tuned, mouse_move=False, pre_click_pause=Jitter()
    )
    forced = behavior_for(session.behavior, True)
    assert forced.type_char_delay == tuned
    assert forced.mouse_move is True
    assert forced.pre_click_pause == Behavior.human().pre_click_pause


# --- which behaviour a call runs under ---


def test_an_explicit_behavior_beats_the_humanize_shorthand(
    session: BrowserSession,
) -> None:
    """A caller holding a `Behavior` has already decided; the shorthand is
    there for callers who are not holding one."""
    session.behavior = Behavior.human()
    assert effective_behavior(session, True, Behavior.off()) == Behavior.off()


def test_the_humanize_shorthand_beats_the_sessions_default(
    session: BrowserSession,
) -> None:
    session.behavior = Behavior.off()
    assert effective_behavior(session, True).mouse_move is True


def test_neither_leaves_the_sessions_default(session: BrowserSession) -> None:
    session.behavior = RATE_LIMITED
    assert effective_behavior(session) is RATE_LIMITED


def test_an_explicit_behavior_drives_the_call(session: BrowserSession) -> None:
    session.click("#btn", behavior=Behavior.human())
    driver(session).humanized_click.assert_called_once()
    driver(session).click.assert_not_called()


def test_a_call_leaves_the_sessions_behavior_alone(session: BrowserSession) -> None:
    """The behaviour a call runs under is the call's; the session's is the
    default it started with, before and after."""
    session.behavior = Behavior.off()
    session.click("#btn", behavior=Behavior.human())
    session.fill("#input", "hello", humanize=True)
    assert session.behavior == Behavior.off()


# --- a click a sticky banner swallowed ---


def clicks_that_fail(session: BrowserSession, failures: int) -> None:
    """The driver's click raises ``failures`` times, then lands."""
    remaining = iter(range(failures))

    def click(element: Any) -> None:
        if next(remaining, None) is not None:
            raise TimeoutError("intercepts pointer events")

    driver(session).click.side_effect = click


def test_an_intercepted_click_is_centred_and_retried(
    session: BrowserSession,
) -> None:
    clicks_that_fail(session, 1)

    session.click("#btn")

    driver(session).scroll_into_view.assert_called_once_with("element")
    assert driver(session).click.call_count == 2


def test_a_click_that_lands_never_scrolls(session: BrowserSession) -> None:
    session.click("#btn")

    driver(session).scroll_into_view.assert_not_called()


def test_a_click_intercepted_twice_reports_the_first_error_and_the_hatch(
    session: BrowserSession,
) -> None:
    clicks_that_fail(session, 2)

    with pytest.raises(TimeoutError) as failure:
        session.click("#btn")

    assert "intercepts pointer events" in str(failure.value)
    assert "dispatch: true" in str(failure.value)


def test_a_failure_that_is_not_an_interception_is_not_retried(
    session: BrowserSession,
) -> None:
    """Centring cannot unlock a disabled control, and the hint would tell the
    caller to dispatch an untrusted click at it."""
    driver(session).click.side_effect = TimeoutError("element is not enabled")

    with pytest.raises(TimeoutError) as failure:
        session.click("#btn")

    assert str(failure.value) == "element is not enabled"
    driver(session).scroll_into_view.assert_not_called()
    assert driver(session).click.call_count == 1


def test_a_centring_failure_leaves_the_click_error_alone(
    session: BrowserSession,
) -> None:
    """The element the click struggled with can make the centring evaluate time
    out too; reporting that would bury why the click never landed."""
    clicks_that_fail(session, 1)
    driver(session).scroll_into_view.side_effect = TimeoutError(
        "locator.evaluate: Timeout 30000ms exceeded"
    )

    with pytest.raises(TimeoutError) as failure:
        session.click("#btn")

    assert str(failure.value) == "intercepts pointer events"


def test_a_retry_that_fails_for_another_reason_reports_that_reason(
    session: BrowserSession,
) -> None:
    errors = iter(
        [TimeoutError("intercepts pointer events"), TimeoutError("element is hidden")]
    )

    def click(_element: Any) -> None:
        raise next(errors)

    driver(session).click.side_effect = click

    with pytest.raises(TimeoutError) as failure:
        session.click("#btn")

    assert str(failure.value) == "element is hidden"


def test_a_library_bug_is_not_retried(session: BrowserSession) -> None:
    driver(session).click.side_effect = AttributeError("bug")

    with pytest.raises(AttributeError):
        session.click("#btn")

    driver(session).scroll_into_view.assert_not_called()


# --- the hit test a humanized click runs after its move ---

COVERED = {
    "target": False,
    "hit": {"tag": "li", "text": "Estados de cuenta", "class_name": "menu-item"},
}
ON_TARGET = {
    "target": True,
    "hit": {"tag": "a", "text": "Salir", "class_name": "headerlogout"},
}
DESCENDANT = {
    "target": True,
    "hit": {"tag": "span", "text": "Salir", "class_name": "label"},
}


CENTRE = (400.0, 300.0)


def humanized_page(
    session: BrowserSession, answer: dict[str, Any], gap: int = 0
) -> Any:
    """Run the real humanized click over a page whose target starts ``gap``
    pixels out of view and which answers ``answer`` when asked what the pointer
    ended up over. One wheel tick lands it, as it would on a real page."""
    session.behavior = Behavior.human()
    element = MagicMock()
    element.bounding_box.return_value = {
        "x": 10.0,
        "y": 20.0,
        "width": 100.0,
        "height": 40.0,
    }
    driver(session).first.return_value = element
    gaps = [gap]

    def evaluate(target: Any, script: str, timeout_ms: int | None = None) -> Any:
        if "getBoundingClientRect" not in script:
            return answer
        return {"gap": gaps.pop(0) if gaps else 0, "centre": list(CENTRE)}

    driver(session).evaluate.side_effect = evaluate
    driver(session).humanized_click.side_effect = behavior_module.humanized_click
    return session.get_page()


def test_humanized_click_aborts_when_covered_after_move(
    session: BrowserSession, sleeps: list[float]
) -> None:
    page = humanized_page(session, COVERED)

    with pytest.raises(ValueError) as failure:
        session.click("#logout")

    assert "covered-after-move" in str(failure.value)
    assert all(part in str(failure.value) for part in ("li", "menu-item", "Estados"))
    page.mouse.down.assert_not_called()
    page.mouse.up.assert_not_called()


def test_covered_click_moves_the_pointer_away_before_refusing(
    session: BrowserSession, sleeps: list[float]
) -> None:
    """A pointer left parked on the menu its own path opened keeps that menu
    open for whatever the caller does next, so it walks off before refusing."""
    page = humanized_page(session, COVERED)
    moves_when_asked: list[int] = []
    fits = driver(session).evaluate.side_effect

    def watched(target: Any, script: str, timeout_ms: int | None = None) -> Any:
        if "getBoundingClientRect" not in script:
            moves_when_asked.append(page.mouse.move.call_count)
        return fits(target, script, timeout_ms)

    driver(session).evaluate.side_effect = watched

    with pytest.raises(ValueError, match="covered-after-move"):
        session.click("#logout")

    assert page.mouse.move.call_count > moves_when_asked[0]
    assert page.mouse.move.call_args.args == CENTRE
    page.mouse.down.assert_not_called()


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (ON_TARGET, HitTarget(tag="a", text="Salir", class_name="headerlogout")),
        # The page owns the containment answer: the span inside the link is the
        # target, so a hit whose tag differs is not a miss.
        (DESCENDANT, HitTarget(tag="span", text="Salir", class_name="label")),
    ],
)
def test_humanized_click_reports_what_the_pointer_was_over(
    session: BrowserSession,
    sleeps: list[float],
    answer: dict[str, Any],
    expected: HitTarget,
) -> None:
    page = humanized_page(session, answer)

    assert session.click("#logout") == expected

    page.mouse.down.assert_called_once()
    # Asked about where the pointer actually stopped, not where `find` looked.
    landed = page.mouse.move.call_args_list[-1].args
    assert json.dumps(list(landed)) in driver(session).evaluate.call_args.args[1]


def test_offscreen_target_is_wheeled_into_view_before_the_move(
    session: BrowserSession, sleeps: list[float]
) -> None:
    """A target below the fold would be clicked at the clamped viewport edge,
    on whatever sits there — and a page that jumps in one frame with no wheel
    events is the tell, so the pointer wheels it in instead."""
    page = humanized_page(session, ON_TARGET, gap=320)

    session.click("#logout")

    driver(session).scroll.assert_called_once()
    scrolled_page, dx, dy = driver(session).scroll.call_args.args
    assert (scrolled_page, dx) == (page, 0)
    assert abs(dy - 320) <= round(320 * Behavior.human().scroll_delta_jitter)
    driver(session).scroll_into_view.assert_not_called()
    # The path only starts once the box is in view.
    called = [name for name, *_ in driver(session).method_calls]
    assert called.index("scroll") < called.index("humanized_click")


def test_target_in_view_is_not_scrolled(
    session: BrowserSession, sleeps: list[float]
) -> None:
    humanized_page(session, ON_TARGET)

    session.click("#logout")

    driver(session).scroll.assert_not_called()
    driver(session).scroll_into_view.assert_not_called()


def test_a_hit_test_that_cannot_run_fails_the_step(
    session: BrowserSession, sleeps: list[float]
) -> None:
    """A navigation during the dwell destroys the context; pressing blind is
    the failure the gate exists to stop, so it fails as a step instead."""
    page = humanized_page(session, ON_TARGET)

    def destroyed(target: Any, script: str, timeout_ms: int | None = None) -> Any:
        if "getBoundingClientRect" in script:
            return {"gap": 0, "centre": list(CENTRE)}
        raise RuntimeError("Execution context was destroyed")

    driver(session).evaluate.side_effect = destroyed

    with pytest.raises(ValueError, match="hit-test-failed"):
        session.click("#logout")

    page.mouse.down.assert_not_called()
    # Bounded: a detached target must not buy the driver's 30 s default with
    # the pointer sitting on the page.
    assert driver(session).evaluate.call_args.kwargs["timeout_ms"] > 0
