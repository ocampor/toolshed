# Changelog

## Unreleased

### Added

- `BrowserSession.save_screenshot(path)` and `BrowserSession.scroll(dx, dy)`.
- `behavior.paced(behavior, runtime)` — brackets one interaction with its gap and post-action pause; nested scopes defer to the outermost one.

### Changed

- `BrowserSession` owns input: `click(selector, dispatch=False)`, `fill(selector, value)`, `type(selector, value, delay_ms=0)`, `press(selector | None, key)`, `select_option(selector, value)` and `set_checked(selector, checked)` each wait for the element, apply the `Behavior` pacing and pick the humanized or the plain driver primitive.
- The `click`/`fill`/`type`/`press`/`select`/`check` actions are one line each onto those methods; `actions.py`, `steps.py` and `flows.py` no longer touch `session.driver`, and a test asserts it against the source.
- `session.click("#go")` from Python gets the same humanization a flow step gets; `session.find("#go").click()` still bypasses it.
- `pick` and `download_file` click the way a `click` step does.
- `BehaviorRuntime` is reachable as `session.behavior_runtime` (was `session._behavior_runtime`).
- `behavior.paced` replaces the `enforce_gap` / `post_pause` / `mark_action_done` sequence callers spelled out.

### Fixed

- A YAML schema's `type:` string is parsed against an allowlist (`schema_types.resolve_type`) instead of `eval`-ed against `typing`.

## 0.8.0 — 2026-09-09

### Added

- `BrowserSession.wait_for_element(selector, state=, timeout=, interval=, settle=)`, the `wait_for` flow step and the `llm-browser wait-for` CLI command — the one wait for `attached`/`detached`/`visible`/`hidden`/`stable` (text unchanged for `settle` ms); `find`, `find_all`, `frame` and `element_exists` all go through it.
- `Driver.is_visible(locator)` backs the `visible`/`hidden` states.
- `FlowError.outputs` — outputs collected before a failing step (including inside a sub-flow) are no longer thrown away.
- `BrowserSession.screenshot_bytes()`; `Driver.screenshot_bytes` has a non-abstract default.
- `llm_browser.flow_repository`: `FlowRepository` protocol, `FileFlowRepository`, `DictFlowRepository`, `LayeredFlowRepository`.
- `flow_pipeline.resolve_flow` / `resolve_flow_text` — the async, I/O-only reference-resolution stage.
- `flows.load_flow_document(document, *, selector_map=None)` — the pure validation stage.
- `RunFlowStep.flow` accepts an inline child flow (`SubFlow`), so a flow needs no repository when its children are embedded.
- `flows.with_flow_path(result, path)`.

### Changed

- `load_flow_text` raises `ValueError("invalid flow yaml: ...")` instead of leaking `yaml.YAMLError`.
- `run` / `validate` resolve their flow through `cli.resolve_flow_options` under `asyncio.run`; an empty `--flow ''` is now a usage error.
- `Driver`'s class docstring is now the five-rule driver contract; `DriverHandle`, `DriverNotInstalledError`, `load_optional_module` moved to `llm_browser.drivers.handle` (still re-exported from `llm_browser.drivers`).
- `_resolve_with_fallback` probes the primary branch with the now non-waiting `count`.

### Breaking

- `Driver.count(locator)` and `Driver.text_content(locator)` never wait — they answer "right now"; on nodriver, `count`/`find_all` no longer block up to 10s for a late element.
- `flows.load_flow_text(text)` drops `subflow_loader`, `subflows`, `base_dir` and `selector_map`; validation itself takes no context at all.
- `RunFlowStep.flow` is now `SubFlow | str`; `RunFlowStep.subflow` is gone — the child lives in `flow`.
- `BrowserSession.goto` / `launch` / `launch_detached` reject non-`http(s)` URLs by default; pass `allowed_schemes=` to opt back in.
- `run-flow` references are resolved by a `FlowRepository` (`flow_pipeline.resolve_flow`) before validation; a flow loaded from text no longer resolves siblings from the filesystem.
- An unknown selector `ref:` raises `ValueError` instead of pydantic `ValidationError`; a missing flow file raises `FlowNotFoundError` instead of `FileNotFoundError`.

### Removed

- `wait` step, `BrowserSession.wait_until_stable`, `Driver.wait_for_stable_text`, `Driver.wait_for_state`.
- `llm_browser.flow_files` (`load_flow`, `run_flow_file`), `llm_browser.subflows` (`subflow_source`).
- `flow_pipeline.FlowSource`, `build_flow`, `subflow_refs`, `run_flow_ref`, `parse_flow_document`, the `SubflowLoader` alias; `SelectorMap` moved to `llm_browser.selector_map`.

### Migration

- `wait` step → `wait_for` with `state: stable` (`quiet_ms`→`settle`, `timeout_s`→`timeout` ms)
- explicit element waits → `wait_for_element` / the `wait_for` step
- `flow_files.load_flow` (removed) → `resolve_flow` + `load_flow_document`
- `count` no longer waits on nodriver — use `wait_for_element` instead
- `goto` accepts `http`/`https` only by default — pass `allowed_schemes=` to opt out
- `parse_flow_document` removed — `parse_flow_yaml` is the one parser

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
