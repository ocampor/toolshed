# Driver Stealth Details

The llm-browser README has the 3-row summary. This page has the anti-bot
landscape and each driver's fine print.

## Anti-bot landscape

`Behavior.human()` is **timing-only** humanization: inter-key gaps, click jitter, mouse paths,
pre/post action pauses. It applies to every `BrowserSession` input method — `click`, `fill`,
`type`, `press`, `select_option`, `set_checked`, `pick`, `download_file` (which returns the
file's bytes, never writes them) — and so to the flow steps built on them:
`session.click("#go")` gets the same humanization a `click` step gets.
Calls on a raw driver locator or page (`session.find(...)`, `session.get_page()`) bypass it.

Timing humanization does NOT modify runtime JS fingerprints (navigator, WebGL, canvas, CDP
detection). Those are the driver's job:

- `patchright` removes Playwright automation fingerprints but still runs a freshly-launched
  Chromium — OK for moderate bot detection.
- `camoufox` spoofs fingerprints at the C++ level — good for most fingerprint-grade targets
  (DataDome, PerimeterX).
- For the hardest targets (Cloudflare JSD on high-traffic sites, Akamai Bot Manager) a launched
  automation context will often lose no matter how much stealth is applied. The supported path
  is **attach mode** (`docs/ATTACH.md` in the llm-browser package): launch Chromium yourself with a warmed
  profile and connect to it over CDP.

Generic bot-test pages (bot.sannysoft.com, arh.antoinevastel.com) don't predict real-world
outcomes against specific vendors — always probe the actual target.

The 2026 measurements behind that advice — and the finding that attach mode voids patchright's
patches — are in `docs/RESEARCH.md` in the llm-browser package.

## Selector and key support

Not every selector form or key reaches every backend. Both gaps below fail *quietly enough to
ship a wrong value*, so pick the driver before you pick the selector.

| Capability | `patchright` | `camoufox` | `nodriver` |
|---|---|---|---|
| CSS selector | yes | yes | yes |
| XPath (`{ xpath: ... }`) | yes | yes | **no** — `resolve` hands the string to `tab.select` / `query_selector_all`, a bare `DOM.querySelectorAll`, and an `xpath=//...` string is not valid CSS |
| `FallbackSelector` | yes | yes | yes, if both branches are CSS |
| `press` named keys (`Enter`, `Tab`, `Escape`, `Backspace`, `Delete`, arrows) | yes | yes | yes |
| `press` chords (`Control+a`) | yes | yes | **no** — anything outside `NAMED_KEYS` goes to `el.send_keys(key)`, which **types the literal text `Control+a` into the field and reports success** |
| `download` step / `download_file` | yes | yes | **no** — `download_bytes` raises `NotImplementedError` |

On `nodriver`, reach a label-anchored control with CSS instead: `:has()` and attribute selectors
cover most of what a `//label[...]/following::…` XPath was doing, and an id with the
prefix-healing pattern covers the rest.

## Headless caveat

Chromium-based drivers (`patchright`, `nodriver`) leak `HeadlessChrome` in the User-Agent and
fall back to SwiftShader for WebGL when run headless — both are cheap detection signals. For
fingerprint-grade targets, run them headed (or under Xvfb). `camoufox` spoofs UA and WebGL even
in headless mode and is the only viable headless option against strict detectors. See
`scripts/stealth_probe.py` to reproduce.

## Writing a driver

A driver is any subclass of `llm_browser.drivers.base.Driver` that implements every abstract
method — `BrowserSession`, the flow actions and `llm_browser.waits` are written against that
ABC, not against a browser API. Its class docstring is the contract, and the five rules in it
are the parts a new backend gets wrong: which methods may block on the DOM (only
`wait_for_load` — every read answers about the page as it is now), that input must be trusted
events, which methods may run JS, that `first`/`nth` stay re-resolvable, and that timeouts are
milliseconds and raise the builtin `TimeoutError`. Capture returns bytes, never a path:
`screenshot_bytes(page)` hands back PNG and `download_bytes(page, trigger)` a `BytesResult`, so
a backend whose API can only write a file spools it to a temporary directory and removes it
before returning. `screenshot_element_bytes(locator)` is the same capture cropped to one
element; it is the one capture method that is not abstract, so a page-only backend leaves it
raising `NotImplementedError` and the conformance suite reports a skip. `tests/test_driver_contract.py` checks the read rules against each driver with
fakes; add yours to its fixture. Conformance suite:
`packages/llm-browser-conformance` (separate package, in progress).

## nodriver — detectable surfaces

Default paths are not synthetic. A small set of reads/polls still use `Runtime.callFunctionOn`
because CDP exposes no equivalent:

| Surface | Mechanism | Why it stays |
|---|---|---|
| `input_value` | JS read of `.value` | CDP has no live-property accessor; `attrs["value"]` is the HTML attribute and diverges after typing. |
| `set_checked` | JS read of `.checked` | Same — read before click avoids flipping an already-correct checkbox. |
| `wait_for_load` | Polls `document.readyState` every 250ms | nodriver 0.48 has no CDP lifecycle hook; `tab.wait()` is a plain sleep. |
| `read` / `parse` extraction | JS read of `el.<property>` (`textContent`, `value`, …), one `Runtime.callFunctionOn` per property field per row | One rule for every property name, shared with `js/extract_rows.js`, so what a spec means cannot differ by backend. The cost is real: a 50-row × 3-property read is 150 Runtime calls where the old `textContent` shortcut made none. Attribute fields stay on `attrs` — no Runtime traffic. |
| `is_visible` | JS read of `offsetParent` / `getClientRects` | nodriver exposes no visibility API and CDP has no visibility predicate. Only `visible`/`hidden` pay this: `wait_for_element(..., state="attached")` goes through `count` → `tab.query_selector_all`, a bare `DOM.querySelectorAll` with no Runtime traffic and no `Target.getTargets` refresh. |
| `evaluate` / `dom` | User-supplied JS | Intentional. |

These are reads — they dispatch no DOM events and don't trip `isTrusted` checks. Only a
detector that fingerprints Runtime-domain CDP traffic itself would catch them.

Opt-in escape hatches that **do** emit `isTrusted=false` (use sparingly):

- `dispatch_event(locator, event)` — fires `new Event(...)`.
- `click(locator, dispatch=True)` — JS `HTMLElement.click()` for overlay bypass.

## camoufox — stealth defaults

`CamoufoxDriver()` injects these kwargs unless the caller overrides them:

| Default | Why |
|---|---|
| `humanize=True` | C++-level Bezier mouse paths; Playwright's linear interpolation is detectable. |
| `block_webrtc=True` | WebRTC leaks the real IP behind HTTP proxies. |
| `geoip=True` *(conditional)* | Injected only when `locale` is set without any of `geoip` / `timezone` / `geolocation` — aligns timezone + geolocation with the outgoing IP so locale/tz/IP/Accept-Language triangulate consistently. |

Caveats:

- `persistent_context=True` is always on (required for session reuse). If you rotate proxies
  between runs but reuse `user_data_dir`, cookies and storage link the sessions across IPs —
  rotate the user-data dir for fresh identities.
- Pinning `locale` on an IP that doesn't match its region (e.g. `locale="fr-FR"` on a US IP)
  still misaligns — caller intent can't be inferred. Pin `timezone` and `geolocation` explicitly
  or use a matching proxy.
