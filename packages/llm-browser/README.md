# llm-browser

Playwright browser automation with declarative YAML flows, designed for LLM-driven agents.

## Architecture

A flow is loaded before it is run — every `run-flow` reference gets inlined
first, so the rest of the pipeline never touches disk or a store again:

```
source (file | text | store)
   │  FlowRepository.get(ref)      FileFlowRepository · DictFlowRepository · LayeredFlowRepository
   ▼
resolve_flow / resolve_flow_text   inline every run-flow child (async, the only I/O)
   ▼
load_flow_document / load_flow_text   pure pydantic validation → Flow
   ▼
run_flow(session, flow, data)
```

Running a flow steps down through four layers, each narrower than the one above:

```
Flow (pydantic)      steps: [GotoStep, ClickStep, WaitForStep, ReadStep, RunFlowStep(SubFlow)…]
   │  run_flow → execute_step (capture on failure, redact, outputs)
   ▼
actions              registry action name → fn(session, step) -> ActionResult      one per step type
   │
   ▼
BrowserSession       goto · find · wait_for_element · dom · probe · parse_elements · screenshot
   │  selector resolution, waits (waits.py), sanitization (html.py), probe JS, behavior pacing
   ▼
Driver (ABC)         resolve/count/first/is_visible/text_content · click/fill/type/press · goto/wait_for_load · evaluate · screenshot
   │  contract: no DOM waits (only wait_for_load blocks), trusted input, JS only in evaluate/is_visible/input_value/extract_rows
   ▼
patchright | camoufox | nodriver
```

- **Flow** — the validated pydantic document and its steps; owns templating, `when` conditions, and stitching results together, never calls a driver directly.
- **actions** — a registry that maps a step to session calls, one function per action name; several also reach `session.driver` directly for the interaction itself.
- **BrowserSession** — selector resolution, `waits.py` polling loops, `html.py` sanitization, probe scripts and behavior pacing; owns *how* to wait, never blocks inside a `Driver` call itself.
- **Driver (ABC)** — the one abstraction over browser backends: no DOM-aware waiting except `wait_for_load`, only trusted input events, and JS confined to `evaluate`, `is_visible`, `input_value` and `extract_rows`.
- **patchright / camoufox / nodriver** — concrete drivers implementing the ABC; adding a backend means implementing every abstract method and holding to the same five rules.

Waiting: the five `wait_for` states are documented in [FLOWS.md](FLOWS.md#waiting).
Writing a driver: start from the contract in the `Driver` class docstring, `src/llm_browser/drivers/base.py`.

## Install

```bash
cd packages/llm-browser
uv sync
```

## Usage

### Python API

```python
from llm_browser import BrowserSession

session = BrowserSession()
session.launch("https://example.com", headed=True)

# Find and interact
session.fill("#username", "admin")
session.fill("#password", "secret")
session.click("button[type=submit]")

# Check element presence
if session.element_exists("#dashboard"):
    print("Logged in")

# Wait for an element to turn up, or for one to go away
session.wait_for_element("#results", state="visible", timeout=10_000)
session.wait_for_element(".modal-backdrop", state="detached", timeout=5_000)

# Wait for text that is still moving to hold still
session.wait_for_element("#isr-total", state="stable", settle=800, timeout=20_000)

# Read page structure
html = session.dom("body", max_depth=2)

# Extract data
data = session.parse_elements("tr.row", {
    "name": {"child_selector": "td.name", "attribute": "textContent"},
    "email": {"child_selector": "td.email", "attribute": "textContent"},
})

session.close()
```

### Typed extraction

For Python callers who'd rather get coerced typed instances than dicts of
strings, declare a model with `ExtractField` defaults and use the classmethods
on `ParseBase`:

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

Pydantic handles validation and type coercion (`"42"` → `int 42`,
`"true"` → `bool`, etc.). The YAML `read` action keeps using the dict shape
shown above — pick whichever fits.

#### From a YAML schema

If you'd rather declare the schema in YAML than in Python, point `build_model`
at a schema file. The returned class is indistinguishable from a hand-written
`ParseBase` subclass — same `extract_all` / `extract_one` call site.

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
assert isinstance(repos[0].stars, int)
```

`type` strings are evaluated against `typing` + Python builtins, so `str`,
`int`, `int | None`, `Optional[int]`, `list[str]`, etc. all work. A given
schema lives in *one* place — Python or YAML, not both.

#### From a YAML flow

A YAML flow can use the same schema via the `parse` action — same shape as
`read`, but rows come back as typed schema instances instead of raw strings:

```yaml
- name: list_repos
  action: parse
  selector: "article.Box-row"
  schema_path: "schemas/repo.yaml"   # CWD-relative or absolute
```

The resulting `ParsedResult.rows` are `Repo` instances (built from the
schema), with values coerced by Pydantic — same outcome as calling
`Repo.extract_all(session, ...)` from Python. Empty rows (every field
None) come back as `None`, mirroring `read`'s behavior.

### CLI

```bash
llm-browser open --url https://example.com
llm-browser goto --url https://example.com/page2
llm-browser find --selector "#form"
llm-browser wait-for --selector "#results" --state visible --timeout 10000
llm-browser wait-for --selector ".cart .total" --state stable --settle 1500 --timeout 30000
llm-browser find-all --selector "li.item"
llm-browser dom --selector "#content" --max-depth 2
llm-browser screenshot
llm-browser close
```

### YAML Flows

```bash
llm-browser run --flow login.yaml --data '{"user": "admin", "pass": "secret"}'
llm-browser run --flow-yaml "$(cat login.yaml)" --data '{}'   # or --flow -
llm-browser resume --data '{"confirm": true}'
```

Loading a flow is three stages — `resolve_flow` (async, the only stage
that does I/O: it inlines every `run-flow` reference through a
`FlowRepository`), `load_flow_document` to validate the result into a
`Flow`, then `run_flow` to execute it. The repository is the only piece
that differs between consumers, so a flow never has to exist on disk:
`FileFlowRepository(base_dir)` reads from a directory,
`DictFlowRepository(flows)` from flows already in hand, and
`LayeredFlowRepository(*layers)` takes the first layer that has the
reference — a service typically layers one request's flows over its own
store, `LayeredFlowRepository(DictFlowRepository(request_flows), store)`.
`redact` scrubs the listed values from the retry hint, error payload,
outputs (a `FlowError` carries the ones collected before the failing
step), and log records.

```python
from llm_browser.flow_pipeline import resolve_flow_text
from llm_browser.flow_repository import FileFlowRepository
from llm_browser.flows import load_flow_document, run_flow

document = await resolve_flow_text(yaml_text, FileFlowRepository(Path.cwd()))
flow = load_flow_document(document)
result = run_flow(session, flow, {"password": pw}, redact=[pw])
result.outputs["headlines"]   # every read / parse / dom step's result
```

See [FLOWS.md](FLOWS.md) for the complete flow language reference.

## Anti-bot landscape

`Behavior.human()` is **timing-only** humanization: inter-key gaps, click
jitter, mouse paths, pre/post action pauses. It only applies to actions
routed through `execute_action(...)` (i.e. YAML flow steps or
`session.pick/goto/find`-based interactions). Calls on the raw
`Page`/`Locator` returned by `session.get_page()` bypass humanization.

Timing humanization does NOT modify runtime JS fingerprints (navigator,
WebGL, canvas, CDP detection). Those are the driver's job:

- `patchright` removes Playwright automation fingerprints but still runs
  a freshly-launched Chromium — OK for moderate bot detection.
- `camoufox` spoofs fingerprints at the C++ level — good for most
  fingerprint-grade targets (DataDome, PerimeterX).
- For the hardest targets (Cloudflare JSD on high-traffic sites, Akamai
  Bot Manager) a launched automation context will often lose no matter
  how much stealth is applied. The supported path is **attach mode**
  (below): launch Chromium yourself with a warmed profile and connect
  to it over CDP.

Generic bot-test pages (bot.sannysoft.com, arh.antoinevastel.com) don't
predict real-world outcomes against specific vendors — always probe the
actual target.

### Headless caveat

Chromium-based drivers (`patchright`, `nodriver`) leak `HeadlessChrome`
in the User-Agent and fall back to SwiftShader for WebGL when run
headless — both are cheap detection signals. For fingerprint-grade
targets, run them headed (or under Xvfb). `camoufox` spoofs UA and
WebGL even in headless mode and is the only viable headless option
against strict detectors. See `scripts/stealth_probe.py` to reproduce.

## Attach mode

Attach `llm-browser` to a Chromium you launched yourself (e.g. a
day-to-day profile that's already passed Cloudflare challenges). The
remote browser is never killed on `close()` — only the tab we opened
and the CDP connection are released.

```bash
chromium --remote-debugging-port=9222 \
         --user-data-dir="$HOME/.cache/llm-browser/attach-profile"
```

```python
from llm_browser import BrowserSession

session = BrowserSession(driver="patchright")
session.attach("http://localhost:9222")
session.goto("https://chatgpt.com")
# ... interact ...
session.close()  # disconnects only — your Chromium keeps running
```

Only the `patchright` driver supports attach; others raise
`NotImplementedError`.

### Addressing a tab by CDP target id

`attach` returns the `target_id` of the tab it opened. `(cdp_url,
target_id)` is the full address of that tab: pass both as global options
and every command drives it — no `state.json`, so parallel callers each
own their tab and never land on someone else's.

```bash
llm-browser --cdp-url http://127.0.0.1:9223 attach          # -> {"target_id": "..."}
llm-browser --cdp-url http://127.0.0.1:9223 --target-id ABC goto --url https://example.com
llm-browser --cdp-url http://127.0.0.1:9223 --target-id ABC close
```

`close` here releases only that tab; the Chromium keeps running. If the
tab was closed meanwhile, commands fail with `Tab ABC not found`.

### One-shot remote run

`run --cdp-url` does the whole cycle in one command: attach to the
running Chromium in a fresh tab, run the flow, release the tab (the
browser keeps running). The run is stateless and its tab is addressed by
target id, so several can run in parallel against the same Chromium.

```bash
llm-browser run --cdp-url http://127.0.0.1:9223 \
    --flow flows/warm-site.yml --data '{"url":"https://en.wikipedia.org"}'
```

### Automated detached spawn (`daemon`)

If you don't want to manage Chromium yourself but still need multi-CLI
sessions, use the detached-spawn helper. It launches Chromium in a new
process group (survives Python exit) and attaches over CDP in one step:

```bash
llm-browser daemon --url https://example.com
llm-browser goto --url https://example.com/page2
llm-browser screenshot
llm-browser stop          # actually kills the detached Chromium
```

```python
session = BrowserSession(driver="patchright")
session.launch_detached(url="https://example.com")
# ... later, even from another process:
session = BrowserSession(driver="patchright")
session.connect()          # reattaches via persisted CDP URL
# ... eventually:
session.stop_detached()    # kills the browser we spawned
```

**Caveat.** Daemon-spawned Chromium runs `connect_over_cdp`, which does
not activate patchright's stealth patches. Value comes from reusing a
**warmed** profile across CLI calls — log in / pass Cloudflare once in
that profile and the browser carries cookies and TLS state forward.
For strict detectors, prefer the manual attach recipe above against a
profile you've warmed by hand.

### CLI: single-process vs multi-invocation

The `patchright` driver launches Chromium in-process (required for its
stealth patches to apply). That has one practical consequence for CLI
use:

- **Launched mode is single-process.** `llm-browser open --url ...`
  then a follow-up `llm-browser screenshot` in a separate shell command
  will fail — Chromium died with the first Python process. Use
  `llm-browser run --flow x.yaml --url ...` to launch, run, and close
  end-to-end in one invocation. Or use the Python API.
- **Attach mode is multi-invocation safe.** Your Chromium keeps running
  between CLI calls, so `llm-browser attach --cdp-url ...` followed by
  any number of separate `llm-browser run` / `screenshot` / `close`
  commands works — each reconnects via the persisted CDP URL.

For long-running interactive sessions, use attach mode.

## Capture modes

`BrowserSession(capture=...)` controls what gets captured when a flow
step fails (and on the result):

| Mode | Enables | On-disk paths |
|---|---|---|
| `"screenshot"` (default) | `session.take_screenshot()` | `<session_dir>/screenshot.png` |
| `"dom"` | `session.take_dom_snapshot()` | `<session_dir>/dom.html` |
| `"both"` | both | both |

`<session_dir>` is `<state_dir>/sessions/<session_id>` (default
`/tmp/llm-browser/sessions/default`) and is logged at INFO on first
`launch()` / `attach()`. The user-data-dir inside it is never
auto-removed — call `session.close(cleanup=True)` to remove the
screenshot/DOM files, or delete the session dir yourself to start fresh.

## Architecture

Four layers, each one talking only to the next: steps -> actions -> session ->
driver. A step is what a flow file says; an action turns one step into one
session call; the session decides what that means — wait for the element,
apply the `Behavior` pacing, choose the humanized or the plain primitive — and
the driver is the only layer that knows a browser API. **Actions never see the
driver.** An action that reached for `session.driver` would skip the waiting,
the pacing and the humanization that make a run look human, so
`tests/test_actions.py` asserts on the source of `actions.py`, `steps.py` and
`flows.py` that none of them touches a `driver` attribute at all.

Every click in the package goes through one branch, `session_input.click_element`
— humanized, plain or dispatched — including the ones `pick` and `download_file`
resolve for themselves, so how a run looks never depends on which action a flow
reached for.

The session's input half lives in `llm_browser/session_input.py`;
`BrowserSession.click` / `fill` / `type` / `press` / `select_option` /
`set_checked` are one-line delegations to it, and they are the same methods the
`click`, `fill`, `type`, `press`, `select` and `check` actions call.

## Drivers

Three browser drivers, selected via object injection or a string name:

| Driver | Install | Engine | Stealth notes |
|---|---|---|---|
| `patchright` (default) | base install | Chromium (patched Playwright) | Removes Playwright automation fingerprints; uses Playwright's humanization helpers. |
| `camoufox` | `pip install llm-browser[camoufox]` | Firefox (Camoufox) | C++-level fingerprint spoofing. Playwright-compatible API. Stealth defaults on (humanize, block_webrtc, locale→geoip auto-alignment). |
| `nodriver` | `pip install llm-browser[nodriver]` | Chromium via raw CDP | All writes (click, type, fill, focus) go through real `Input.dispatchMouseEvent` / `dispatchKeyEvent` / `DOM.focus` — events are `isTrusted=true`. |

```python
# String lookup
session = BrowserSession(driver="nodriver")

# Object injection (lets you pass driver-specific config)
from llm_browser.drivers.camoufox import CamoufoxDriver
session = BrowserSession(driver=CamoufoxDriver(locale="fr-FR", humanize=True))
```

### Writing a driver

A driver is any subclass of `llm_browser.drivers.base.Driver` that implements
every abstract method — `BrowserSession`, the flow actions and
`llm_browser.waits` are written against that ABC, not against a browser API.
Its class docstring is the contract, and the five rules in it are the parts a
new backend gets wrong: which methods may block on the DOM (only
`wait_for_load` — every read answers about the page as it is now), that input
must be trusted events, which methods may run JS, that `first`/`nth` stay
re-resolvable, and that timeouts are milliseconds and raise the builtin
`TimeoutError`. `tests/test_driver_contract.py` checks the
read rules against each driver with fakes; add yours to its fixture.

### nodriver — detectable surfaces

Default paths are not synthetic. A small set of reads/polls still use
`Runtime.callFunctionOn` because CDP exposes no equivalent:

| Surface | Mechanism | Why it stays |
|---|---|---|
| `input_value` | JS read of `.value` | CDP has no live-property accessor; `attrs["value"]` is the HTML attribute and diverges after typing. |
| `set_checked` | JS read of `.checked` | Same — read before click avoids flipping an already-correct checkbox. |
| `wait_for_load` | Polls `document.readyState` every 250ms | nodriver 0.48 has no CDP lifecycle hook; `tab.wait()` is a plain sleep. |
| `is_visible` | JS read of `offsetParent` / `getClientRects` | nodriver exposes no visibility API and CDP has no visibility predicate. Only the `visible`/`hidden` states pay this: `wait_for_element(..., state="attached")` goes through `count` → `tab.query_selector_all`, a bare `DOM.querySelectorAll` with no Runtime traffic and no `Target.getTargets` refresh. |
| `evaluate` / `dom` | User-supplied JS | Intentional. |

These are reads — they dispatch no DOM events and don't trip `isTrusted`
checks. Only a detector that fingerprints Runtime-domain CDP traffic itself
would catch them.

Opt-in escape hatches that **do** emit `isTrusted=false` (use sparingly):

- `dispatch_event(locator, event)` — fires `new Event(...)`.
- `click(locator, dispatch=True)` — JS `HTMLElement.click()` for overlay bypass.

### camoufox — stealth defaults

`CamoufoxDriver()` injects these kwargs unless the caller overrides them:

| Default | Why |
|---|---|
| `humanize=True` | C++-level Bezier mouse paths; Playwright's linear interpolation is detectable. |
| `block_webrtc=True` | WebRTC leaks the real IP behind HTTP proxies. |
| `geoip=True` *(conditional)* | Injected only when `locale` is set without any of `geoip` / `timezone` / `geolocation` — aligns timezone + geolocation with the outgoing IP so locale/tz/IP/Accept-Language triangulate consistently. |

Caveats:

- `persistent_context=True` is always on (required for session reuse). If you rotate proxies between runs but reuse `user_data_dir`, cookies and storage link the sessions across IPs — rotate the user-data dir for fresh identities.
- Pinning `locale` on an IP that doesn't match its region (e.g. `locale="fr-FR"` on a US IP) still misaligns — caller intent can't be inferred. Pin `timezone` and `geolocation` explicitly or use a matching proxy.

## Known warnings

Every browser launch prints one Node deprecation warning to stderr:

```
DeprecationWarning: `url.parse()` behavior is not standardized... (DEP0169)
    at .../patchright/driver/package/lib/utilsBundleImpl/index.js:8:4476
```

The call originates from patchright's vendored HTTP bundle (during CDP connect), not llm-browser. It is harmless and upstream-tracked; do not suppress it with `NODE_NO_WARNINGS=1` — it is the kind of signal we want surfaced if a future Node version turns it into an error. Confirmed on patchright 1.58.2 (latest as of writing).

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
| `dom(selector, max_depth)` | Cleaned HTML snippet |
| `parse_elements(selector, extract)` | Extract structured data |
| `take_screenshot()` | Screenshot to file |
| `screenshot_bytes()` | Screenshot as PNG bytes, no file written |
| `get_page()` | Raw Playwright Page |
| `frame(selector)` | Enter iframe |
| `wait_for_load_state(state)` | Wait for page load |
| `latest_tab()` | Switch to newest tab |
