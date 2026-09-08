# Changelog

## 0.6.0

### Added

- `load_flow_text(text, *, subflow_loader=None, selector_map=None)` — parse a
  flow from YAML text. `run-flow` references that aren't existing files are
  resolved by calling `subflow_loader(ref)`, which returns the child's YAML
  text, so a whole flow tree can run without touching disk. A non-file
  reference with no loader raises `ValueError`.
- `run_flow(session, flow, data, *, from_step=None, redact=())` runs an
  already-loaded `Flow`; it never reads a file. `RetryHint.flow_path` is empty
  for such a run.
- `llm_browser.flow_files` — the path-based convenience layer over the core:
  `load_flow(path, *, selector_map=None)` (moved here from `llm_browser.flows`)
  and `run_flow_file(session, path, data, *, selector_map=None, from_step=None,
  redact=())`, which loads the file, runs it, and fills `RetryHint.flow_path`
  in from the path it was given. This is what the CLI uses.
- `llm-browser run` / `llm-browser validate` accept the flow as YAML text:
  `--flow-yaml TEXT`, or `--flow -` to read it from stdin. Exactly one of
  `--flow` / `--flow-yaml` is required.
- `FlowSuccess.outputs` — what every `read` / `parse` / `dom` step produced,
  keyed by qualified step name, whether or not the step sets `path:`.
  Screenshots stay paths on disk.
- `run_flow(..., redact=[...])` — replaces the listed secret values with `***`
  in `RetryHint.data`, `RetryHint.error`, the `FlowError` payload, `outputs`,
  and every `llm_browser` log record emitted during the run.
  (`llm_browser.redact.redact_secrets` is the reusable helper.)

### Changed

- **Breaking:** `run_flow`'s second parameter is now a `Flow` model named
  `flow` (was `flow_path`), and its `selector_map=` keyword is gone (apply the
  map at load time). Callers that pass a path should switch to
  `llm_browser.flow_files.run_flow_file`, which keeps the old behavior
  including `RetryHint.flow_path`.
- **Breaking:** `load_flow` moved from `llm_browser.flows` to
  `llm_browser.flow_files`; `load_flow_text` stays in `llm_browser.flows`.
- `execute_step` returns the step's `ActionResult` on success (a
  `SkippedResult` when `when:` skips it) instead of `None`; failures still
  return a `FlowError`.
- A nested `run-flow` inside a sub-flow is now rejected without loading the
  grandchild, so a cyclic reference reports the leaf-only rule instead of
  recursing.

## Unreleased

### Added

- `BrowserSession.launch_detached(url, headed)` + `stop_detached()` — spawn a
  Chromium that survives Python exit and auto-attach over CDP. Gives every
  driver-equivalent path a multi-CLI session story without requiring users
  to manage Chromium by hand.
- `llm-browser daemon` / `llm-browser stop` CLI subcommands.
- `chrome.spawn_detached_chromium()` — reusable helper that spawns Chromium
  in a new process group and returns `(pid, cdp_url)` once
  `DevToolsActivePort` appears.

### Notes

- Detached spawn uses `connect_over_cdp` and so does **not** activate
  patchright stealth. The win is profile warmth: log in / clear Cloudflare
  once in the spawned profile and every subsequent CLI call reuses the
  cookies and TLS state. For strict detectors, keep launching Chromium
  yourself against a human-warmed profile.

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
