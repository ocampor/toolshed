# llm-browser patch — YAML behavior config

## Context

Phase A wants humanized typing / mouse / click timing for every
`llm-browser` CLI invocation (`run --flow`, `click`, `fill`, `press`,
etc.). The CLI has no `--behavior` flag today, so every command runs
with `Behavior.off()` — exactly the regression we hit on the first
real scrape attempt (instant typing, pixel-perfect clicks).

This plan is an upstream patch to `llm-browser` (in
`/home/ocampor/Workspace/toolshed/packages/llm-browser`) that exposes
`Behavior` as a YAML config file via a CLI flag. Independent of the
scraper but blocking Phase A's end-to-end run.

## Goals

1. One CLI flag (`--behavior-config <path>`) on the main group so
   every subcommand's `BrowserSession` inherits the same humanization.
2. Driver-aware defaults — camoufox overrides the Playwright mouse
   fields (`mouse_move`, `focus_drift`) to `False` since its own
   C++ Bézier owns mouse humanization.
3. Pydantic does all the work: type validation, discriminated-union
   dispatch by `driver`, `extra="forbid"` catches typos.
4. Empty YAML → human defaults for the chosen driver.
5. Opt-in only — no env-var fallback, no implicit magic.

## Design (locked)

`BehaviorConfigBase` **inherits `Behavior`**. `Behavior`'s own field
defaults ARE the human values (`Behavior.human()` is just `Behavior()`
with all defaults), so inheriting gives us human-out-of-the-box for
free — no separate preset mechanism, no model validator, no
`as_behavior()` conversion.

```python
# src/llm_browser/behavior_config.py
from pathlib import Path
from typing import Annotated, Literal, Union

import yaml
from pydantic import ConfigDict, Field, TypeAdapter, ValidationError

from llm_browser.behavior import Behavior


class BehaviorConfigError(ValueError):
    """Raised when a behavior config file is malformed."""


class BehaviorConfigBase(Behavior):
    """Inherits Behavior. Subclasses declare a `driver` literal as
    the pydantic discriminator. No extra model validators — Behavior's
    field types and the union dispatch handle all validation.

    Behavior's field defaults are the human values (Behavior.human()
    is Behavior() with defaults), so an empty YAML yields human
    behavior on patchright out of the box. Programmatic callers who
    want off / pace can pass Behavior.off() / Behavior.pace() to
    BrowserSession directly."""
    model_config = ConfigDict(frozen=True, extra="forbid")


class PlaywrightBehaviorConfig(BehaviorConfigBase):
    driver: Literal["patchright", "nodriver"] = "patchright"


class CamoufoxBehaviorConfig(BehaviorConfigBase):
    driver: Literal["camoufox"]
    # Camoufox's native C++ Bézier mouse paths would clash with the
    # Playwright-level mouse move/drift; default these off so a bare
    # `driver: camoufox` YAML gives natural behavior. Users who know
    # what they're doing can set them True explicitly.
    mouse_move: bool = False
    focus_drift: bool = False


BehaviorConfig = Annotated[
    Union[PlaywrightBehaviorConfig, CamoufoxBehaviorConfig],
    Field(discriminator="driver"),
]
_ADAPTER: TypeAdapter = TypeAdapter(BehaviorConfig)


def load_behavior(config_path: str | Path) -> Behavior:
    """Parse YAML → a `BehaviorConfigBase` subclass instance (which
    IS-A `Behavior`, so it passes straight to `BrowserSession`).

    If `driver` is absent the loader fills `patchright` before
    validation — pydantic discriminated unions require the tag in
    the data."""
    data = yaml.safe_load(Path(config_path).read_text()) or {}
    if isinstance(data, dict):
        data.setdefault("driver", "patchright")
    try:
        return _ADAPTER.validate_python(data)
    except ValidationError as e:
        raise BehaviorConfigError(f"{config_path}: {e}") from e
```

```python
# src/llm_browser/cli.py — additions only
@click.option("--behavior-config", "behavior_config", default=None,
              help="YAML humanization config. See llm_browser.behavior_config.")
def main(ctx, session_id, driver_name, behavior_config):
    driver = driver_name or os.environ.get(DRIVER_ENV_VAR)
    behavior = None
    if behavior_config:
        try:
            behavior = load_behavior(behavior_config)
        except BehaviorConfigError as e:
            raise click.ClickException(str(e)) from e
    ctx.obj["session"] = BrowserSession(
        session_id=session_id, driver=driver, behavior=behavior,
    )
```

### YAML UX examples

```yaml
# empty → human behavior on patchright (Behavior defaults)
```
```yaml
driver: camoufox
# → human timing/typing; mouse_move=False, focus_drift=False
```
```yaml
driver: camoufox
mouse_move: true    # explicit opt-in, overrides the False default
focus_drift: true
```
```yaml
# "off-like" — user sets what they want off explicitly:
mouse_move: false
focus_drift: false
fill_as_type: false
type_char_delay: {min_ms: 0, max_ms: 0}
```

## Files to change

In `/home/ocampor/Workspace/toolshed/packages/llm-browser`:

- **New** `src/llm_browser/behavior_config.py` — ~40 lines total.
- **Modified** `src/llm_browser/cli.py` — add `--behavior-config`
  group option; wrap `load_behavior` call in
  `try/except BehaviorConfigError → ClickException`.
- **New** `tests/test_behavior_config.py`.

Nothing in `llm-scraper` changes as part of this patch.

## Reused primitives

- `llm_browser.behavior.Behavior` — the parent class. Pydantic model
  with human-like defaults; provides `.off()` / `.pace()` / `.human()`
  classmethods for programmatic use. (`behavior.py:40`)
- `llm_browser.session.BrowserSession(session_id, driver, behavior)`
  — accepts `behavior=None` (treats as off). `BehaviorConfigBase`
  instances pass through as-is because they ARE `Behavior` subclasses.
  (`session.py:29`)
- `pydantic.TypeAdapter` + `Annotated[Union[...], Field(discriminator=...)]`
  — native discriminated-union dispatch.

## Known trade-offs (accepted)

1. **No `preset: off|pace|human` YAML shortcut.** Users who want
   non-human from YAML write individual fields. Programmatic callers
   use `Behavior.off()` / `.pace()` directly. Cost: YAML verbosity
   for off/pace configs; benefit: ~80 lines of preset machinery
   removed.
2. **Camoufox silently accepts `mouse_move_steps` / `click_offset_px`.**
   They're inherited from `Behavior` so `extra="forbid"` doesn't
   reject them, but the camoufox driver ignores them. Small footgun;
   rejecting would require a per-subclass validator that rebuilds
   what we just removed. Accept the no-op; document in the module
   docstring.
3. **Loader `setdefault("driver", "patchright")`** is the single
   non-pydantic line in the module. Could be a `model_validator`
   on the union wrapper, but a single-line loader helper is simpler
   and clearer.

## Verification

1. `cd /home/ocampor/Workspace/toolshed/packages/llm-browser`
2. `uv run --with pytest pytest tests/test_behavior_config.py -v`
   — all green. Test matrix:
   - Empty YAML → `Behavior.human()` on patchright.
   - Missing `driver` → defaults to patchright.
   - Explicit `driver: patchright` / `driver: nodriver` / `driver: camoufox`.
   - Camoufox defaults: `mouse_move=False`, `focus_drift=False`; timing fields match human.
   - Camoufox user re-enables mouse_move / focus_drift via YAML.
   - Unknown driver rejected with `BehaviorConfigError`.
   - Unknown field rejected (`extra="forbid"`).
   - Wrong type rejected.
   - Returned instance is a `Behavior` (isinstance check).
3. `uv run --with pytest pytest tests/ -q` — full suite still green.
4. From `llm-scraper/` after `uv sync`:
   `uv run llm-browser --session chatgpt --driver patchright --behavior-config behavior.yaml status`
   — prints `{status: …}` with no behavior-related error.

## Working-tree status

The current in-flight `toolshed` working tree still has the OLD
shape (`BehaviorConfigBase(BaseModel)` with `_seed_from_preset`
validator + `as_behavior()` method + `preset_exclude` ClassVar +
concrete defaults). Implementation of this plan will **replace**
that shape with the one above. No commits to revert; changes are
all staged/uncommitted.

## Out of scope

- Wiring the scraper's `behavior.yaml` into SKILL.md / scraper CLI
  invocations — follow-up once this patch merges.
- Extending `Behavior` itself (adding fields, renaming things).
- Per-command behavior overrides.
- Adding more presets / factory classmethods on the config.
