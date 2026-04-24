"""BehaviorConfig discriminated union + load_behavior.

Config classes inherit from Behavior, so their defaults are the
human values. An empty YAML yields Behavior.human() on patchright;
the camoufox subclass overrides the Playwright-level mouse fields
to False so a bare `driver: camoufox` gives natural behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_browser.behavior import Behavior
from llm_browser.behavior_config import (
    BehaviorConfigError,
    CamoufoxBehaviorConfig,
    PlaywrightBehaviorConfig,
    load_behavior,
)


def write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "behavior.yaml"
    p.write_text(body)
    return p


# ---- Discriminator dispatch ----


def test_empty_yaml_gives_human_on_patchright(tmp_path: Path) -> None:
    b = load_behavior(write(tmp_path, ""))
    assert isinstance(b, PlaywrightBehaviorConfig)
    assert isinstance(b, Behavior)
    human = Behavior.human()
    assert b.type_char_delay == human.type_char_delay
    assert b.mouse_move is True
    assert b.focus_drift is True


def test_no_driver_defaults_to_patchright(tmp_path: Path) -> None:
    b = load_behavior(write(tmp_path, "min_gap_ms: 500\n"))
    assert isinstance(b, PlaywrightBehaviorConfig)
    assert b.min_gap_ms == 500


def test_explicit_patchright(tmp_path: Path) -> None:
    b = load_behavior(write(tmp_path, "driver: patchright\n"))
    assert isinstance(b, PlaywrightBehaviorConfig)


def test_explicit_nodriver(tmp_path: Path) -> None:
    b = load_behavior(write(tmp_path, "driver: nodriver\n"))
    assert isinstance(b, PlaywrightBehaviorConfig)
    assert b.driver == "nodriver"


def test_explicit_camoufox_forces_mouse_off(tmp_path: Path) -> None:
    b = load_behavior(write(tmp_path, "driver: camoufox\n"))
    assert isinstance(b, CamoufoxBehaviorConfig)
    assert b.mouse_move is False
    assert b.focus_drift is False
    assert b.type_char_delay == Behavior.human().type_char_delay


def test_unknown_driver_rejected(tmp_path: Path) -> None:
    with pytest.raises(BehaviorConfigError):
        load_behavior(write(tmp_path, "driver: future-driver\n"))


# ---- Overrides ----


def test_shared_override(tmp_path: Path) -> None:
    p = write(
        tmp_path,
        """
driver: patchright
min_gap_ms: 1500
type_char_delay: {min_ms: 20, max_ms: 80}
""",
    )
    b = load_behavior(p)
    assert b.min_gap_ms == 1500
    assert b.type_char_delay.min_ms == 20
    assert b.type_char_delay.max_ms == 80


def test_playwright_user_disables_mouse_move(tmp_path: Path) -> None:
    p = write(tmp_path, "driver: patchright\nmouse_move: false\nfocus_drift: false\n")
    b = load_behavior(p)
    assert b.mouse_move is False
    assert b.focus_drift is False


def test_camoufox_can_re_enable_mouse_move(tmp_path: Path) -> None:
    p = write(tmp_path, "driver: camoufox\nmouse_move: true\nfocus_drift: true\n")
    b = load_behavior(p)
    assert b.mouse_move is True
    assert b.focus_drift is True


def test_off_like_config(tmp_path: Path) -> None:
    p = write(
        tmp_path,
        """
mouse_move: false
focus_drift: false
fill_as_type: false
type_char_delay: {min_ms: 0, max_ms: 0}
""",
    )
    b = load_behavior(p)
    assert b.mouse_move is False
    assert b.focus_drift is False
    assert b.fill_as_type is False
    assert b.type_char_delay.min_ms == 0
    assert b.type_char_delay.max_ms == 0


# ---- Validation errors ----


def test_unknown_field_rejected(tmp_path: Path) -> None:
    with pytest.raises(BehaviorConfigError):
        load_behavior(write(tmp_path, "typoed_field: true\n"))


def test_wrong_type_rejected(tmp_path: Path) -> None:
    with pytest.raises(BehaviorConfigError):
        load_behavior(write(tmp_path, "fill_as_type: sometimes\n"))


# ---- Config classes usable directly ----


def test_playwright_defaults_match_human() -> None:
    c = PlaywrightBehaviorConfig()
    human = Behavior.human()
    assert c.type_char_delay == human.type_char_delay
    assert c.mouse_move == human.mouse_move
    assert c.focus_drift == human.focus_drift


def test_camoufox_defaults_forces_mouse_off() -> None:
    c = CamoufoxBehaviorConfig(driver="camoufox")
    assert c.mouse_move is False
    assert c.focus_drift is False
    assert c.type_char_delay == Behavior.human().type_char_delay


def test_returned_instance_is_behavior(tmp_path: Path) -> None:
    b = load_behavior(write(tmp_path, ""))
    assert isinstance(b, Behavior)
