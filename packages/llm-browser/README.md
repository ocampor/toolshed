# llm-browser

Playwright browser automation with declarative YAML flows, designed for LLM-driven agents.

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
session.find("#username").fill("admin")
session.find("#password").fill("secret")
session.find("button[type=submit]").click()

# Check element presence
if session.element_exists("#dashboard"):
    print("Logged in")

# Read page structure
html = session.dom("body", max_depth=2)

# Extract data
data = session.parse_elements("tr.row", {
    "name": {"child_selector": "td.name", "attribute": "textContent"},
    "email": {"child_selector": "td.email", "attribute": "textContent"},
})

session.close()
```

### CLI

```bash
llm-browser open --url https://example.com
llm-browser goto --url https://example.com/page2
llm-browser find --selector "#form"
llm-browser find-all --selector "li.item"
llm-browser dom --selector "#content" --max-depth 2
llm-browser screenshot
llm-browser close
```

### YAML Flows

```bash
llm-browser run --flow login.yaml --data '{"user": "admin", "pass": "secret"}'
llm-browser resume --data '{"confirm": true}'
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

`BrowserSession(capture=...)` controls what gets captured at each flow
checkpoint:

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

### nodriver — detectable surfaces

Default paths are not synthetic. A small set of reads/polls still use
`Runtime.callFunctionOn` because CDP exposes no equivalent:

| Surface | Mechanism | Why it stays |
|---|---|---|
| `input_value` | JS read of `.value` | CDP has no live-property accessor; `attrs["value"]` is the HTML attribute and diverges after typing. |
| `set_checked` | JS read of `.checked` | Same — read before click avoids flipping an already-correct checkbox. |
| `wait_for_load` | Polls `document.readyState` every 250ms | nodriver 0.48 has no CDP lifecycle hook; `tab.wait()` is a plain sleep. |
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

## Session methods

| Method | Description |
|--------|-------------|
| `launch(url, headed)` | Launch Chrome and connect |
| `attach(cdp_url)` | Connect to an already-running Chromium over CDP |
| `launch_detached(url, headed)` | Spawn detached Chromium + auto-attach (multi-CLI safe) |
| `stop_detached()` | Kill a detached Chromium spawned by `launch_detached` |
| `close(cleanup=False)` | Close session; attach/detached keep the browser alive |
| `wait_until_stable(sel, quiet_ms, timeout_s)` | Wait for textContent to stop changing (streaming replies) |
| `goto(url)` | Navigate |
| `find(selector)` | Find exactly one element (returns Playwright Locator) |
| `find_all(selector)` | Find all matching elements |
| `element_exists(selector)` | Check if element is present |
| `pick(selector, value)` | Click list item matching text |
| `dom(selector, max_depth)` | Cleaned HTML snippet |
| `parse_elements(selector, extract)` | Extract structured data |
| `take_screenshot()` | Screenshot to file |
| `get_page()` | Raw Playwright Page |
| `frame(selector)` | Enter iframe |
| `wait_for_load_state(state)` | Wait for page load |
| `latest_tab()` | Switch to newest tab |
