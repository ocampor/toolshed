"""YAML behavior-config loader with driver-specific subclasses.

Clients must pass a config path explicitly; there is no env-var
fallback. Absent config path → the caller falls back to
``Behavior.off()``.

The config classes inherit from :class:`Behavior` directly, so their
field defaults ARE the human values (``Behavior.human()`` is
``Behavior()`` with defaults). An empty YAML therefore yields human
behavior on patchright out of the box — no preset mechanism, no
conversion step. Programmatic callers who want ``off`` or ``pace``
can pass ``Behavior.off()`` / ``Behavior.pace()`` to
:class:`BrowserSession` directly.

Two subclasses, split by driver:

- :class:`PlaywrightBehaviorConfig` — patchright / nodriver. All
  Behavior fields apply (timing, typing, mouse move/drift).
- :class:`CamoufoxBehaviorConfig` — camoufox's native C++ Bézier
  owns mouse humanization, so ``mouse_move`` and ``focus_drift``
  default to ``False`` here. Users can set them ``True`` explicitly.
  Note that ``mouse_move_steps`` and ``click_offset_px`` are still
  accepted by the schema (inherited from Behavior) but are a no-op
  on camoufox when ``mouse_move`` is False.

Raises :class:`BehaviorConfigError` (subclass of :class:`ValueError`)
on a malformed config — CLI callers catch this and re-raise as
``click.ClickException``; other callers can handle it natively.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Union

import yaml
from pydantic import ConfigDict, Field, TypeAdapter, ValidationError

from llm_browser.behavior import Behavior


class BehaviorConfigError(ValueError):
    """Raised when a behavior config file is malformed."""


class BehaviorConfigBase(Behavior):
    """Behavior subclass used as the pydantic discriminated-union
    base. Subclasses add a ``driver`` literal as the discriminator;
    all other validation comes from Behavior's field types plus
    ``extra="forbid"`` (typo-safe)."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class PlaywrightBehaviorConfig(BehaviorConfigBase):
    """For patchright / nodriver. All Behavior defaults apply."""

    driver: Literal["patchright", "nodriver"] = "patchright"


class CamoufoxBehaviorConfig(BehaviorConfigBase):
    """For camoufox. Camoufox's native C++ Bézier handles mouse
    humanization, so the Playwright-level mouse fields default to
    ``False`` here. Users can re-enable them explicitly."""

    driver: Literal["camoufox"]
    mouse_move: bool = False
    focus_drift: bool = False


BehaviorConfig = Annotated[
    Union[PlaywrightBehaviorConfig, CamoufoxBehaviorConfig],
    Field(discriminator="driver"),
]
_ADAPTER: TypeAdapter[PlaywrightBehaviorConfig | CamoufoxBehaviorConfig] = TypeAdapter(
    BehaviorConfig
)

DEFAULT_DRIVER = "patchright"


def load_behavior(config_path: str | Path) -> Behavior:
    """Parse a YAML config into a :class:`Behavior`. The returned
    instance is a ``BehaviorConfigBase`` subclass (so IS-A Behavior)
    and passes straight to :class:`BrowserSession`.

    If ``driver`` is absent, the loader fills in the default tag
    before validation — pydantic discriminated unions require a
    tag in the data."""
    data = yaml.safe_load(Path(config_path).read_text()) or {}
    if isinstance(data, dict):
        data.setdefault("driver", DEFAULT_DRIVER)
    try:
        return _ADAPTER.validate_python(data)
    except ValidationError as e:
        raise BehaviorConfigError(f"{config_path}: {e}") from e
