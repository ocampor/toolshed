# Changelog

## Unreleased

### Added

- `BrowserSession.wait_for_element(selector, *, state="attached", timeout=3000,
  interval=500)` — an explicit wait in the shape of Selenium's
  `WebDriverWait.until`: a Python poll loop that asks the cheapest driver
  primitive whether the state is reached, sleeps `interval` ± 30 %
  (`POLL_JITTER_RATIO`), and raises `TimeoutError("<selector> did not become
  <state> within <timeout>ms")` when the deadline passes. `timeout` is a
  budget rather than a floor: each sleep is clamped to what is left of it, so
  the wait overruns by at most one state check and `timeout=0` is exactly one
  check. The message renders the selector the way it was written (`#id`,
  `xpath=...`, `#a or #b` for a fallback chain), not as a pydantic repr. Bad
  budgets are rejected at flow-load time — `timeout >= 0`, `interval > 0` —
  instead of surfacing mid-poll as a `Jitter` error. It never hands the
  wait to the driver: on the Playwright family that runs an injected in-page
  script, and a fixed 500 ms cadence is itself a fingerprint.
  `attached`/`detached` are answered by `driver.count` — a plain DOM query, no
  `Runtime.evaluate` on nodriver; `visible`/`hidden` by `Driver.is_visible`,
  which is Playwright's `locator.is_visible()` and, on nodriver, an
  `offsetParent`/`getClientRects` read (it is abstract on `Driver`, so a new
  driver cannot forget it). The locator is re-resolved every tick, so a node the page swapped out
  is still seen to change state — with a `FallbackSelector` that also means
  the branch can change mid-wait, so `detached` is judged against whichever
  branch matched this tick and will not fire while the fallback still
  matches. An error from a tick propagates: a CDP failure is not "not yet".

  It is the only wait left: `find`, `find_all`, `frame` and `element_exists`
  all go through it, and `element_exists` is the one caller that reads its
  timeout back as a `bool` instead of letting it raise.
- `wait_for` flow step (`state`, `timeout`, `interval`) — the explicit-wait
  counterpart to `wait`, which waits for an element's *text* to stop changing.
  A timeout fails the step the same way every other step failure is reported:
  a `FlowError` carrying the screenshot, the DOM snapshot and `human_needed`,
  with the selector/state/timeout message as its `data.message`. `optional:
  true` downgrades a never-appearing element to a skip.
- **Breaking:** `Driver.count(locator)` never waits — it answers how many
  elements match *right now*, so a poll tick cannot stall inside the driver.
  On nodriver, `count`/`find_all` no longer wait up to 10 s for a late
  element; use `wait_for_element`, which `find`, `find_all` and `frame` now
  call before they resolve anything. `count` there was
  `tab.select_all(selector)`, whose retry cycle costs a 500 ms sleep plus a
  `Target.getTargets` refresh apiece and is paid even at `timeout=0`, because
  the timeout is only checked after the first cycle; it is now
  `tab.query_selector_all` — the bare `DOM.querySelectorAll` underneath it,
  no retry, no sleep, no target refresh. Nothing is cached on the locator
  either, so every read sees the page as it is.
- `llm-browser wait-for --selector S [--state] [--timeout] [--interval]` — the
  same wait from the CLI; a timeout exits non-zero with the message, no
  traceback.

### Changed

- The `Driver` ABC's class docstring is now the driver contract: five rules
  covering what may block on the DOM, that input must be trusted events,
  which methods may run JS, what `first`/`nth` have to survive, and that
  timeouts are milliseconds raising the builtin `TimeoutError`. The read
  rules are checked against every driver by `tests/test_driver_contract.py`.
  To keep `base.py` the contract and nothing else, `DriverHandle`,
  `DriverNotInstalledError` and `load_optional_module` moved to
  `llm_browser.drivers.handle` and the Python text-stability poll to
  `llm_browser.drivers.stable_text`. `llm_browser.drivers` re-exports all
  three names as before; only `from llm_browser.drivers.base import
  load_optional_module` (or `DriverNotInstalledError`) has to change.
- `_resolve_with_fallback` probes the primary branch with the now
  non-waiting `count`. It was always asking "does the primary match right
  now", and every caller waits for the state it wants afterwards; on nodriver
  the old waiting `count` made resolution of a fallback selector block for
  ~10 s whenever the primary was absent — once per tick inside an explicit
  wait.

### Fixed

- `FLOWS.md` described `wait` as a page-load-state wait with `state` /
  `timeout` params and filed it under "Page actions". It has been the
  text-stability wait (`quiet_ms` / `timeout_s`, selector required) for
  several releases; the reference now says so and lists it with the other
  element actions.

## 0.8.0 — 2026-09-09

### Added

- `BrowserSession.wait_for_element(selector, state=..., timeout=..., interval=...)`
  — one wait that covers all four `WaitState` values (`attached`, `detached`,
  `visible`, `hidden`) on every driver, and the only wait: `find`, `find_all`,
  `frame`, `element_exists` and the `wait_for` step all go through it, so a
  state means the same thing whichever one you call. `element_exists(selector)`
  is that wait with the timeout read as `False` rather than raising, so
  `element_exists("#missing")` returns `False` instead of raising.
- `Driver.is_visible(locator)` — whether the first match is rendered right
  now, `False` if nothing matches. On nodriver it is
  `offsetParent !== null || getClientRects().length > 0` evaluated on the
  element: nodriver exposes no visibility API and CDP has no visibility
  predicate, so a read is the honest option. It is what the `visible` and
  `hidden` states poll, in place of the driver-native waits — `Driver.wait_for_state`
  and its Playwright and nodriver implementations are gone. Those ran an
  injected in-page script on the Playwright family, and on nodriver `visible`
  reported a `display:none` element as found and `detached` returned at once.
- `flows.subflow_refs(text)` — lists the `run-flow` references in a flow
  without validating its steps. An async caller (an HTTP or MCP server that
  fetches children over the network) can now discover every child up front,
  await them all, and hand the results to `load_flow_text(..., subflows=...)`,
  instead of being forced into a synchronous `subflow_loader` callback in the
  middle of pydantic validation. Malformed documents yield `[]` rather than
  raising — validation stays `load_flow_text`'s job — but bad YAML still
  raises `ValueError`.
- `load_flow_text(..., subflows=...)` — an explicit ref → YAML-text mapping,
  threaded through the validation context. It takes precedence over
  `subflow_loader`, so a caller that already has the children in hand does not
  need a loader at all.
- `FlowError.outputs` — the outputs collected before the failing step, keyed
  by qualified step name exactly like `FlowSuccess.outputs`. A flow that read
  three pages and then failed on the fourth used to throw all three results
  away, forcing a full re-run to see any of them; the caller can now use the
  partial data (or show it to the user) while deciding whether to retry. A
  failure inside a sub-flow keeps both the parent's earlier outputs and the
  child's — including an `optional:` sub-flow, whose swallowed failure now
  hands its partial outputs back to the parent — and `redact` scrubs them on
  the same pass as a success's.
- `BrowserSession.screenshot_bytes()` → `bytes` — the current page as PNG
  bytes, with nothing written into the session dir. A server that only wants
  to hand the image back had to call `take_screenshot()` and read the file it
  wrote; on Playwright the bytes now come straight from `page.screenshot()`.
  `Driver.screenshot_bytes` is non-abstract: its default writes to a temp file
  through the driver's own `screenshot()` and reads it back, so drivers whose
  screenshot API only writes files (nodriver) get a working implementation
  without an override. `take_screenshot()` is unchanged.
- `llm_browser.flow_repository` — `FlowRepository`, a protocol with a single
  `async def get(ref) -> str` returning a flow's YAML text (or raising
  `FlowNotFoundError(ref)`), plus `FileFlowRepository(base_dir)` which reads
  relative refs under `base_dir` and honours absolute ones. The repository is
  the only part of flow loading that differs between consumers.
- `DictFlowRepository(flows)` — a mapping of reference → YAML text — and
  `LayeredFlowRepository(*layers)`, which takes the first layer that has the
  reference and raises `FlowNotFoundError(ref)` when none does. A consumer
  that accepts child flows with a request layers them over its own store:
  `LayeredFlowRepository(DictFlowRepository(request_flows), store)`. Only a
  `FlowNotFoundError` falls through to the next layer; anything else
  propagates, and `FileFlowRepository` reports a miss only for a missing path
  (a permission or I/O error propagates).
- `flow_pipeline.resolve_flow(ref, repo)` / `resolve_flow_text(text, repo)` —
  stage one, async and the only stage that does I/O. They parse the YAML and
  inline every `run-flow` reference as the child's document, fetching children
  concurrently and once per distinct reference. A child that references a flow
  of its own is rejected here, so leaf-only no longer depends on validation
  context.
- `flows.load_flow_document(document, *, selector_map=None)` — stage two, pure:
  it validates an already-resolved document into a `Flow`. The selector map is
  a parameter applied to the document (parent steps and any embedded child),
  not a validation-context key.
- `run-flow` steps take the child flow inline: `flow:` accepts the child's own
  mapping (`params:` / `steps:`), so a flow with embedded children needs no
  repository at all.
- `flows.with_flow_path(result, path)` — fills `retry_hint.flow_path` for a
  flow that came from a file (moved from the deleted `flow_files`).

### Changed

- **Breaking:** `run-flow` references in a flow loaded with
  `load_flow_text` no longer resolve from the filesystem. Resolution used to
  try an on-disk file first and fall back to `subflow_loader`, which meant
  flow text from stdin, `--flow-yaml` or an API request could read arbitrary
  YAML off the local disk, and which child you got depended on the current
  working directory. There is now one order — `subflows` mapping, then
  `subflow_loader`, then `base_dir` — and only `flow_files.load_flow` supplies
  a `base_dir`. So file-loaded flows resolve siblings exactly as before, and
  text-loaded flows resolve only through what the caller passed in; a
  reference with no mapping entry, no loader and no `base_dir` raises
  `ValueError` naming the reference. `load_flow_text(..., base_dir=...)` lets a
  caller opt back in explicitly, and the CLI passes `base_dir=Path.cwd()` for
  `--flow -` and `--flow-yaml`: someone piping a flow into `llm-browser run` or
  `llm-browser validate` does have a meaningful working directory, so sibling
  refs keep resolving there while every library caller stays off the filesystem
  until it names a directory.
- `load_flow_text` and `flow_files.load_flow` now raise
  `ValueError("invalid flow YAML: ...")` instead of leaking `yaml.YAMLError`,
  so a caller has one exception type to catch for malformed input, and a
  malformed flow *file* fails the same way as malformed flow *text*.
  Pydantic's `ValidationError` and anything raised by `subflow_loader` still
  propagate untouched — a loader that signals a missing child with its own
  exception type keeps working.
- `BrowserSession.goto`, `launch` and `launch_detached` now validate the URL
  scheme before they touch the browser and raise `ValueError` for anything
  outside `DEFAULT_URL_SCHEMES`
  (`http`, `https`). A flow step or an LLM-supplied URL could previously reach
  `file:///etc/passwd`, `chrome://settings` or `javascript:` and have the
  browser act on it; a schemeless relative path is rejected for the same
  reason. Every caller shares one validation path —
  `llm_browser.session.checked_url()` — so the flow `goto` action and
  `llm-browser goto` inherit the guard, and a rejected step surfaces as an
  ordinary step failure with the offending URL in the message. The two launch
  paths validate before they start anything, so a bad URL cannot leave an
  orphaned detached Chromium behind; `url=None` stays legal for both. Pass
  `allowed_schemes=` to opt a specific call back in, e.g.
  `allowed_schemes=("file",)` for local fixture pages.
- **Breaking:** `RunFlowStep.flow` is now `SubFlow | str` and `RunFlowStep.subflow`
  is gone — the child lives in `flow`. A `flow:` that is still a string fails
  validation with `unresolved sub-flow <ref>: resolve it through a
  FlowRepository first`.
- **Breaking:** `flows.load_flow_text(text)` no longer takes `subflow_loader`,
  `subflows`, `base_dir` or `selector_map`; it validates text that has nothing
  left to resolve. Sub-flow resolution goes through a `FlowRepository`, and
  selector maps through `load_flow_document(..., selector_map=...)`.
- **Breaking:** removed `llm_browser.flow_files` (`load_flow`, `run_flow_file`),
  `llm_browser.subflows` (`subflow_source`), `flow_pipeline.FlowSource`,
  `build_flow`, `subflow_refs`, `run_flow_ref`, `parse_flow_document` and the
  `SubflowLoader` alias. `parse_flow_yaml(text)` is the one parser both stages
  use, and `SelectorMap` now lives in `llm_browser.selector_map`.
- **Breaking:** validation takes no context at all — the `subflows`,
  `subflow_loader`, `base_dir`, `selector_map` and `in_subflow` keys are gone.
- A flow document that is not a mapping raises
  `ValueError("invalid flow yaml: expected a mapping, got ...")`.
- An unknown selector `ref:` now raises `ValueError` instead of a pydantic
  `ValidationError` (it is expanded before validation), and a missing flow file
  raises `FlowNotFoundError` instead of `FileNotFoundError`.
- The `run` and `validate` commands resolve their flow through
  `cli.resolve_flow_options` (replacing `flow_source_from_options`) and run it
  under `asyncio.run`. A file resolves its references against its own
  directory; `--flow -` and `--flow-yaml` use the CWD. An empty `--flow ''` is
  a usage error rather than a silent cwd lookup.
- Parse errors read `ValueError("invalid flow yaml: ...")`, replacing
  `"invalid flow YAML: ..."`.

## 0.7.0 — 2026-09-09

### Added

- `BrowserSession.launch_detached(url, headed)` + `stop_detached()` — spawn a
  Chromium that survives Python exit and auto-attach over CDP. Gives every
  driver-equivalent path a multi-CLI session story without requiring users
  to manage Chromium by hand.
- `llm-browser daemon` / `llm-browser stop` CLI subcommands.
- `chrome.spawn_detached_chromium()` — reusable helper that spawns Chromium
  in a new process group and returns `(pid, cdp_url)` once
  `DevToolsActivePort` appears.
- `SanitizeLevel` (`low`/`medium`/`high`/`xhigh`) for DOM extraction, wired
  through `BrowserSession.dom(selector, level=...)` and `llm-browser dom
  --level`. Every level is one lxml `Cleaner` over the same options — scripts,
  styles, comments, `svg`/embeds and `meta`/`link` always go — and they differ
  only in which attributes survive. `low` keeps them all; `medium` drops
  custom and decorative attributes; `high` drops every `src` and `href` on
  top, iframes included; `xhigh` keeps only `id`, `alt`, `title`, `role`,
  `type`, `name`, `value`, `placeholder`, and `div`/`span`/`section` wrappers
  are removed (their text and children stay). Each level keeps a subset of
  the one below it. Default stays `low`.
- `BrowserSession.probe(selector=None, max_chars=...)` → `PageProbe`
  (`password_visible`, `challenge`, `text`, `selector_text`): one in-page
  evaluate that reports whether a page is showing a credential prompt or a
  bot challenge. `llm_browser.probe.human_needed(page_probe)` turns that
  into a yes/no, and `probe_from_markup(html)` does the same for a static
  failure snapshot. The challenge-selector list lives in `constants.py` and
  is injected into `js/page_probe.js`, so JS and Python agree by construction.
- `selectors.css_string(selector)` — CSS text for an in-page `querySelector`;
  raises for XPath/fallback selectors, which need a driver locator.
- `FlowError.human_needed` — a failing step now probes the page, so a caller
  can tell "retry later" from "a person has to log in or clear a challenge"
  without re-parsing the DOM snapshot. The probe is diagnostic only: if it
  raises, the field stays `False` and the original error is untouched.
- `ExtractField.parse("child selector@attribute")` and
  `parse.parse_extract_spec({field: spec})` — the compact one-string form of
  an extraction field, for callers taking specs from JSON or a CLI. Either
  half may be omitted: `"td.name"`, `"@href"`, `"td.name@href"`.

### Fixed

- `dom()` no longer rewrites unknown tags: lxml treated `main`, `dialog`,
  `picture`, `template`, `slot` and `path` as unknown and replaced a `main`
  root with a bare attribute-less `div`.
- `dom()` output collapses whitespace runs and drops blank-only text nodes,
  except inside `pre`/`textarea`.

### Notes

- Detached spawn uses `connect_over_cdp` and so does **not** activate
  patchright stealth. The win is profile warmth: log in / clear Cloudflare
  once in the spawned profile and every subsequent CLI call reuses the
  cookies and TLS state. For strict detectors, keep launching Chromium
  yourself against a human-warmed profile.

## 0.6.0

### Added

- `load_flow_text(text, *, subflow_loader=None, selector_map=None)` — parse a
  flow from YAML text; non-file `run-flow` refs go to `subflow_loader`.
- `run_flow(session, flow, data, *, from_step=None, redact=())` — run a loaded
  `Flow`; never reads a file.
- `llm_browser.flow_files` — `load_flow` (moved here) and `run_flow_file`, the
  path-based layer the CLI uses.
- `llm-browser run` / `validate` accept `--flow-yaml TEXT` or `--flow -`
  (stdin); exactly one of `--flow` / `--flow-yaml` is required.
- `FlowSuccess.outputs` — every `read` / `parse` / `dom` result, keyed by
  qualified step name.
- `run_flow(..., redact=[...])` — replaces the listed values with `***` in the
  retry hint, error payload, outputs, and `llm_browser` log records.

### Changed

- **Breaking:** `run_flow` takes a `Flow` (was `flow_path`) and drops
  `selector_map=`; use `flow_files.run_flow_file` for the old behavior.
- **Breaking:** `load_flow` moved from `llm_browser.flows` to
  `llm_browser.flow_files`.
- `execute_step` returns the step's `ActionResult` on success instead of `None`.
- A nested `run-flow` inside a sub-flow is rejected without loading the
  grandchild.

## 0.2.0

### Breaking

- **Patchright launched mode no longer survives across Python processes.**
  The previous subprocess + `connect_over_cdp` pattern bypassed patchright's
  stealth patches (they only apply on `launch` / `launch_persistent_context`).
  Launched mode now uses in-process `launch_persistent_context`, so Chromium
  dies with the Python process that started it.

  **Migration.** Multi-invocation CLI workflows must switch to one of:

  1. **Attach mode** (recommended for long-running sessions):

     ```bash
     chromium --remote-debugging-port=9222 \
              --user-data-dir="$HOME/.cache/llm-browser/attach-profile"
     ```

     ```python
     session = BrowserSession(driver="patchright")
     session.attach("http://localhost:9222")
     ```

     Attach mode reconnects via the persisted CDP URL across CLI calls and
     never kills the remote browser on `close()`.

  2. **Single-shot run** — `llm-browser run --flow x.yaml --url ...` to
     launch, execute, and close in one invocation.

- **Flows with checkpoint steps now require a resumable session.** Running a
  checkpointed flow under launched-mode patchright raises `RuntimeError` up
  front instead of failing opaquely on `resume`. Use attach mode, or remove
  the checkpoint.

### Added

- `BrowserSession.attach(cdp_url)` — connect to a Chromium you launched
  yourself. Only `patchright` supports this; `camoufox` and `nodriver` raise
  `NotImplementedError`.
- `llm-browser attach --cdp-url ...` CLI subcommand.
- `PressStep` / `action_press` — keyboard press action (with or without a
  target selector), routed through `execute_action` so humanization applies.
- `WaitStableStep` / `session.wait_until_stable(selector, quiet_ms, timeout_s)`
  — waits until a node's textContent stops changing (streaming-reply
  primitive for chat scrapers).
- `BrowserSession(executable_path=...)` — override auto-discovered Chromium
  binary.
- `ChromiumNotInstalledError` with actionable install hint when the
  Playwright browser isn't installed.
- `Driver.can_resume_across_processes(handle)` hook — drivers declare per-
  handle whether a session can survive process exit.
- `BrowserSession.close(cleanup=True)` — removes capture artifacts
  (screenshot/DOM) but preserves `user_data_dir`.
- Session dir logged at INFO on `launch()` / `attach()`.
- `scripts/stealth_probe.py` — manual probe runner for sannysoft / creepjs /
  antoinevastel / browserscan / Cloudflare across drivers. Not part of the
  test suite (flaky, rate-limited).

### Changed

- `nodriver.evaluate()` now returns plain JSON instead of CDP RemoteObjects
  — nodriver's `tab.evaluate` hardcodes deep-serialization, so we call
  `Runtime.evaluate` with `returnByValue` directly.
- Camoufox `type()` defaults to jittered per-character rhythm.
- Camoufox callers can override lifecycle kwargs; `fill` emits key events.
- `Behavior.human()` docstring clarifies it covers **timing only** — not
  runtime fingerprints — and only applies to actions routed through
  `execute_action(...)`.

### Known limitations

- Headless Chromium (patchright, nodriver) leaks `HeadlessChrome` in the UA
  and SwiftShader in WebGL. Use headed mode, Xvfb, or switch to `camoufox`
  for headless runs against strict detectors.

## 0.1.0

Initial release.
