# Changelog

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
