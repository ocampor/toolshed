# Python API Reference

See [README → Quickstart](../README.md#quickstart) for the short version. This page has typed
extraction, the full `BrowserSession` method table, and capture-mode details.

## Typed extraction

For Python callers who'd rather get coerced typed instances than dicts of strings, declare a
model with `ExtractField` defaults and use the classmethods on `ParseBase`:

```python
from llm_browser import BrowserSession
from llm_browser.parse import ExtractField, ParseBase


class Repo(ParseBase):
    name:  str = ExtractField(child_selector="h3 a")
    stars: int = ExtractField(child_selector=".stars")
    href:  str = ExtractField(attribute="href")  # off the row itself


session = BrowserSession()
session.launch("https://github.com/trending")
repos: list[Repo] = Repo.extract_all(session, "article.Box-row")
top:   Repo | None = Repo.extract_one(session, "article.Box-row")

assert isinstance(repos[0].stars, int)  # coerced from text
```

Pydantic handles validation and type coercion (`"42"` → `int 42`, `"true"` → `bool`, etc.). The
YAML `read` action keeps using the dict shape — pick whichever fits.

### From a YAML schema

If you'd rather declare the schema in YAML than in Python, point `build_model` at a schema file.
The returned class is indistinguishable from a hand-written `ParseBase` subclass — same
`extract_all` / `extract_one` call site.

```yaml
# schemas/repo.yaml
name: Repo
fields:
  name:
    type: str
    child_selector: "h3 a"
  stars:
    type: int
    child_selector: ".stars"
  description:
    type: str | None              # required → omit `default`; optional → declare it
    child_selector: ".desc"
    default: null
```

```python
from llm_browser.parse import build_model

Repo = build_model("schemas/repo.yaml")
repos = Repo.extract_all(session, "article.Box-row")
```

`type` strings are evaluated against `typing` + Python builtins, so `str`, `int`, `int | None`,
`Optional[int]`, `list[str]`, etc. all work. A given schema lives in *one* place — Python or
YAML, not both.

### From a YAML flow

The `parse` action uses the same schema — same shape as `read`, but rows come back as typed
schema instances instead of raw strings:

```yaml
- name: list_repos
  action: parse
  selector: "article.Box-row"
  schema_path: "schemas/repo.yaml"   # CWD-relative or absolute
```

`ParsedResult.rows` are `Repo` instances built from the schema, values coerced by Pydantic —
same outcome as `Repo.extract_all(session, ...)`. Empty rows (every field `None`) come back as
`None`, mirroring `read`'s behavior.

## Capture modes

`BrowserSession(capture=...)` controls what gets captured when a flow step fails (and on the
result):

| Mode | Enables | On-disk paths |
|---|---|---|
| `"screenshot"` (default) | `session.take_screenshot()` | `<session_dir>/screenshot.png` |
| `"dom"` | `session.take_dom_snapshot()` | `<session_dir>/dom.html` |
| `"both"` | both | both |

`<session_dir>` is `<state_dir>/sessions/<session_id>` (default `/tmp/llm-browser/sessions/default`)
and is logged at INFO on first `launch()` / `attach()`. The user-data-dir inside it is never
auto-removed — call `session.close(cleanup=True)` to remove the screenshot/DOM files, or delete
the session dir yourself to start fresh.

## Session methods

| Method | Description |
|--------|-------------|
| `launch(url, headed)` | Launch Chrome and connect |
| `attach(cdp_url)` | Connect to an already-running Chromium over CDP |
| `launch_detached(url, headed)` | Spawn detached Chromium + auto-attach (multi-CLI safe) |
| `stop_detached()` | Kill a detached Chromium spawned by `launch_detached` |
| `close(cleanup=False)` | Close session; attach/detached keep the browser alive |
| `goto(url)` | Navigate. `http`/`https` only by default; pass `allowed_schemes=("file",)` to opt a call in to another scheme |
| `find(selector)` | Find exactly one element (returns Playwright Locator) |
| `click(selector, dispatch=False)` | Wait for the element, then click it — humanized mouse path when `Behavior.mouse_move`. `dispatch=True` fires an untrusted DOM `click` event instead, for overlays real input cannot reach |
| `fill(selector, value)` | Set a field's value — typed character by character when `Behavior.fill_as_type`, otherwise a single `fill` |
| `type(selector, value, delay_ms=0)` | Type into a field. An explicit `delay_ms` is your own cadence and wins over the behaviour's per-key jitter |
| `press(selector, key)` | Press `key` on the element; `selector=None` presses on whatever holds focus |
| `select_option(selector, value)` | Choose an option in a `<select>` |
| `set_checked(selector, checked)` | Check or uncheck a checkbox |
| `find_all(selector)` | Find all matching elements |
| `wait_for_element(selector, state=, timeout=, interval=, settle=)` | The one wait: polls from Python on a jittered `interval` until the element is `attached` / `detached` / `visible` / `hidden`, or `stable` — its text unchanged for `settle` ms, which is how you wait out streaming replies or a recalculating total. Raises `TimeoutError` naming selector, state and timeout. `timeout` is a real budget — sleeps are clamped to it and `timeout=0` checks once. No in-page script and no driver-native wait |
| `element_exists(selector)` | Whether the element shows up within `timeout` — `wait_for_element(..., state="attached")` with the timeout read as `False` instead of raising |
| `pick(selector, value)` | Click list item matching text |
| `dom(selector, max_depth, level=)` | Cleaned HTML snippet; `level` is a `SanitizeLevel` (`low`/`medium`/`high`/`xhigh`) |
| `parse_elements(selector, extract)` | Extract structured data |
| `download_file(selector, output_path)` | Trigger a download and save it to `output_path` |
| `take_screenshot()` | Screenshot to file |
| `save_screenshot(path)` | Screenshot to an explicit path |
| `screenshot_bytes()` | Screenshot as PNG bytes, no file written |
| `scroll(dx, dy)` | Mouse-wheel scroll |
| `get_page()` | Raw Playwright Page |
| `frame(selector)` | Enter iframe |
| `wait_for_load_state(state)` | Wait for page load |
| `latest_tab()` | Switch to newest tab |
