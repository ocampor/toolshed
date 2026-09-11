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

`type` strings are parsed against an allowlist, never evaluated; anything else raises
`ValueError: unsupported schema type: ...`. A given schema lives in *one* place — Python or
YAML, not both.

| Form | Accepted |
| --- | --- |
| Primitives | `str`, `int`, `float`, `bool`, `Decimal`, `date`, `datetime` |
| Optional | `X \| None`, `Optional[X]` |
| Containers | `list[X]`, `dict[str, X]` (nestable, e.g. `list[dict[str, str]]`) |

### From a YAML flow

The `parse` action uses the same schema — same shape as `read`, but rows come back as typed
schema instances instead of raw strings:

```yaml
- name: list_repos
  action: parse
  selector: "article.Box-row"
  schema_path: "schemas/repo.yaml"   # CWD-relative or absolute
```

`ParsedResult.rows` (`llm_browser.results.ParsedResult`) are `Repo` instances built from the
schema, values coerced by Pydantic — same outcome as `Repo.extract_all(session, ...)`. Empty
rows (every field `None`) come back as `None`, mirroring `read`'s behavior.

## Capture modes

`BrowserSession(capture=...)` controls what a failing flow step carries back on its
`FlowError` — in memory; the library writes no file:

| Mode | What `FlowError` carries |
|---|---|
| `"screenshot"` (default) | `screenshot`: PNG bytes of the failing page |
| `"dom"` | `dom`: the failing page's sanitized HTML, as text |
| `"both"` | both |
| `"none"` | neither |

`BrowserSession(capture_level=...)` decides how hard that DOM snapshot is
sanitized — a `SanitizeLevel` (`low`/`medium`/`high`/`xhigh`), default `high`.
`high` drops every `src` and `href`; `medium` keeps them, for when where the
page would have gone next is what you need. `llm-browser run --capture-level`
sets it, and `dom_snapshot(level=)` overrides it for one call.

`model_dump(mode="json")` base64-encodes `screenshot`; `run_flow(..., redact=[...])` scrubs
`dom` like every other text on the result. Persisting either is the caller's call —
`llm-browser run` does it, into `--capture-dir` (default: the session dir) as `screenshot.png`
and `dom.html`, and prints those paths in place of the base64.

The same rule covers step outputs. `llm-browser run` writes a step's `path:` under `--out-dir`;
a `screenshot` or `download` that declared none is written there anyway, under the name its
payload came with, because base64 on stdout helps nobody. Text and rows without a `path:` stay
inline in the printed JSON. Every written file is reported by its absolute path in place of the
value.

`<session_dir>` is `<state_dir>/sessions/<session_id>` (default `/tmp/llm-browser/sessions/default`)
and is logged at INFO on first `launch()` / `attach()`. It holds session *state*, never output:
`state.json` (how a detached browser is found again) and `user-data/`. The user-data-dir is
never auto-removed (profile reuse is intentional) — delete the session dir yourself to start
fresh.

## Session methods

| Method | Description |
|--------|-------------|
| `launch(url, headed)` | Launch Chrome and connect |
| `attach(cdp_url)` | Connect to an already-running Chromium over CDP |
| `attach_to_tab(cdp_url, target_id)` | Attach to one existing tab, addressed by its CDP target id |
| `launch_detached(url, headed)` | Spawn detached Chromium + auto-attach (multi-CLI safe) |
| `stop_detached()` | Kill a detached Chromium spawned by `launch_detached` |
| `close()` | Close session; attach/detached keep the browser alive |
| `connect()` | Reconnect to the browser recorded in the session state and return its page |
| `status()` | Whether a session is `open` or `closed`, with its CDP URL and target id |
| `goto(url)` | Navigate. `http`/`https` only by default; pass `allowed_schemes=("file",)` to opt a call in to another scheme |
| `find(selector)` | Find exactly one element (returns the driver's locator: a Playwright `Locator` on patchright/camoufox, a `NodriverLocator` on nodriver) |
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
| `probe(selector=None, max_chars=)` | `PageProbe` of the page's human-attention signals in one evaluate; feed it to `probe.human_needed` |
| `evaluate(target, script)` | Run JS against a page or locator |
| `download_file(selector, timeout=)` | Click the element and return what the browser downloaded as a `BytesResult` (`name`, `content`, `media_type`); `timeout` bounds both finding the element and waiting for the download. The payload is held whole in memory — there is no size ceiling — and `name` is the server's filename, so take its basename before writing it. Writing it anywhere is yours to do |
| `screenshot_bytes()` | The current page as PNG bytes; nothing is written |
| `dom_snapshot(level=None)` | Sanitized HTML of the whole current page, as text; `level` defaults to the session's `capture_level` |
| `scroll(dx, dy)` | Mouse-wheel scroll |
| `get_page()` | Raw driver page (a Playwright `Page` on patchright/camoufox, a nodriver `Tab` on nodriver) |
| `frame(selector)` | Enter iframe |
| `wait_for_load_state(state)` | Wait for page load |
| `latest_tab()` | Switch to newest tab |
