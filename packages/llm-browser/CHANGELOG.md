# Changelog

## 0.13.0 — 2026-09-13

### Added

- `level` on the `dom` step: `low` (default), `medium`, `high`, `xhigh`.
- `min_chars` on `read`, `parse` and `dom`, `min_rows` on `read` and `parse`:
  an unmet minimum fails the step with `Expected ≥N …, got M` and the page in
  `capture`. A `min_rows` on a `read` with no `extract` can never be met, so
  the flow is rejected when it loads with `min_rows requires extract`.
- Extract `attribute` reads a DOM property for `innerText`, `tagName`,
  `childElementCount`, `outerHTML`, `innerHTML` (plus `textContent` and
  `value`); every other name stays an HTML attribute.
- `Driver.read_property`, the per-element half of that rule. Every property
  field now goes through it, `textContent` included: on nodriver a `read` costs
  one `Runtime.callFunctionOn` per property field per row where `textContent`
  used to cost none (see `docs/DRIVERS.md`).
- `PICK_MAX_CANDIDATES`: `pick` refuses a selector matching more than 200
  elements with `Expected list items, scanned N`.

### Fixed

- `dom` with `selector: body` (or `html`) raised
  `ParserError: Multiple elements found`; `sanitize_html_fragment` now returns
  the wrapper element itself.
- An unparseable snippet raised `ParserError`, a `SyntaxError` that escaped
  `is_step_failure` and aborted the run; it is a `ValueError` step failure.
  A truncated `<body` parses into a document with no body at all — also a
  `ValueError` now, not an `AttributeError`.
- `ExtractField.parse("")` raised `empty extract spec`; an empty spec is the
  row's own text.

## 0.12.0 — 2026-09-12

### Changed

- Reference docs `FLOWS.md`, `FLOW_PATTERNS.md` and `DRIVERS.md` moved to
  `docs/`; they are no longer shipped in the wheel.

### Breaking

- `llm-browser skill install` / `llm-browser skill show` and the in-package
  Claude skill bundle (`src/llm_browser/skill/`, `llm_browser.skill_install`)
  are removed. Migration: flow-authoring guidance now comes from the env-sync
  `browser-flows` skill
  (https://github.com/ocampor/env-sync, `claude/skills/browser-flows/`),
  installed globally via env-sync.

### Removed

- Top-level pointer file `FLOWS.md` (superseded by `docs/FLOWS.md`).

## 0.11.0 — 2026-09-11

### Removed

- `solve_captcha` step and the `llm_browser.captcha` module
  (`normalize_answer` included).
- `BrowserSession(captcha_reader=)` parameter and the `self.captcha_reader`
  attribute.
- `llm_browser.CaptchaReader` and `llm_browser.ReaderUnavailable` exports.
- `results.CaptchaResult`.
- `ErrorResult.human_needed` — nothing read it once the `solve_captcha` step
  was gone; `FlowError.human_needed` (the page-probe verdict) is unchanged.

The 0.10.0 additions that are not captcha-specific stay: element-scoped
`screenshot: selector:` / `screenshot_bytes(selector)`, the `wait_for`
`state: detached` navigation fix, and `selector_map` `ref:` expansion for any
selector-valued key.

## 0.10.0 — 2026-09-11

### Added

- `solve_captcha` step — crops `image:`, hands the PNG to the session's
  reader, types the normalized answer into `input:`, clicks `submit:` if set,
  and reads the page's verdict: `error:` visible is a rejection and the next of
  `retries:` attempts crops again, `input:` detached and staying gone is
  acceptance. `timeout:` is the whole budget for one verdict, `prompt:` is
  passed through to the reader, and the step's row in `outputs` is
  `{"attempts": n}` — never the answer.
- `BrowserSession(captcha_reader=)` and `llm_browser.CaptchaReader`
  (`(png_bytes, prompt) -> reply`) — the host hands the session one reading
  function and every `solve_captcha` step on it uses that. The default is
  `None` and the CLI passes none, so an unconfigured session fails the step
  with `human_needed` before touching the page.
- `llm_browser.ReaderUnavailable` — raise it from a reader to say no reading is
  possible in this run (a host with a reader wired but no client attached to
  ask). The step stops after that first crop with `human_needed`, rather than
  spending its remaining `retries:` on the same refusal; every other exception
  stays an ordinary retryable failed step.
- `llm_browser.captcha.normalize_answer` — strips everything but letters and
  digits, accepts 3-12 alphanumeric characters, and reads `UNREADABLE` as
  "no answer".
- `results.CaptchaResult(attempts)`.
- `ErrorResult.human_needed` — an action's own verdict that retrying will not
  help; `execute_step` ORs it into `FlowError.human_needed`.
- `screenshot: selector:` and `BrowserSession.screenshot_bytes(selector)` —
  capture one element instead of the viewport.
- `Driver.screenshot_element_bytes(locator)` — not abstract, so a page-only
  backend leaves it raising `NotImplementedError`. Implemented on the
  Playwright family and on nodriver.
- `BrowserSession.element_exists(..., state=)` — the bool wait answers about
  any `WaitState`, not just `attached`.
- `selector_map` `ref:` expansion for any selector-valued step key, so a step
  naming several selectors can use the map for all of them. A `run-flow`
  step's `data:` is exempt — a child's arguments are values, not selectors.

### Fixed

- A `wait_for` with `state: detached` no longer unwinds when the navigation it
  is watching for destroys the execution context mid-poll; that one driver
  message reads as "not gone yet" and the next tick re-asks.

## 0.9.1 — 2026-09-11

- `NodriverDriver.close()` calls `Browser.stop()` directly instead of `self.run(Browser.stop())`.
- `NodriverDriver.close()` cancels and drains any task `Browser.stop()` left pending on the loop before closing it.

## 0.9.0 — 2026-09-10

The library never writes output files. Everything a flow or a session produces
comes back in memory; the caller decides whether any of it reaches disk. Only
`llm-browser` the CLI writes, and `tests/test_no_output_writes.py` reads the
package's own AST to keep it that way.

### Added

- `llm_browser.results` — the action-result models, moved out of
  `llm_browser.actions` so the driver layer can name one without importing the
  action registry. `llm_browser.actions` still re-exports them.
- `results.BytesResult(name, content, media_type)` — what a `download` or a
  `screenshot` step returns, and what lands in `FlowSuccess.outputs` under that
  step's qualified name. `content` stays `bytes` in memory;
  `model_dump(mode="json")` base64-encodes it.
- `BrowserSession.dom_snapshot() -> str` — sanitized HTML of the whole current
  page, as text.
- `llm-browser run --out-dir` (default: the CWD) and `--capture-dir` (default:
  the session dir, as before). The CLI writes each step's `path:` under the out
  dir — templates in the path resolved the way the runner resolves them — and a
  failure's captures under the capture dir. A `screenshot` or `download` with no
  `path:` is still written, under the name its payload came with.
- `llm-browser screenshot --path` (default `<session dir>/screenshot.png`,
  as before).
- `capture="none"` is in `CaptureMode`; it always worked, it was never typed.
- `BrowserSession(capture_level=SanitizeLevel.HIGH)`, `dom_snapshot(level=)` and
  `llm-browser run --capture-level [low|medium|high|xhigh]` — how hard a
  failure's DOM snapshot is sanitized is the caller's decision now, not a
  constant. `high` (the default, and the previous behaviour) drops every `src`
  and `href`, which is right for reading and wrong when where the page would
  have gone next is the thing you need; `medium` keeps them. `sanitize_page_html`
  takes the level and applies the same per-level passes as
  `sanitize_html_fragment` — data-URI truncation at `medium`+, structural
  collapse at `xhigh`, whitespace normalization — via a shared `sanitize_tree`,
  so a page snapshot and a `dom` snippet at the same level agree.
- `llm_browser.state.SessionState` — the session's `state.json`, in its own
  module. It is the only file the library writes, and `state.py` is what the
  no-output-writes guard exempts, rather than all of `session.py`.

### Breaking

- `path:` on `download`, `screenshot`, `read`, `parse` and `dom` is an
  instruction to the CLI. The runner ignores it — an embedding caller reads the
  value out of `outputs` instead. `DownloadStep.path` is optional as a result.
- `FlowError.screenshot` is `bytes | None` (PNG) and `FlowError.dom` is
  `str | None` (sanitized HTML text). Neither is a path. `redact=` scrubs the
  failure DOM along with the rest of the result.
- `BrowserSession.take_screenshot()`, `save_screenshot(path)` and
  `take_dom_snapshot()` are removed; `screenshot_bytes()` and `dom_snapshot()`
  replace them. `download_file(selector)` returns a `BytesResult` and no longer
  takes an output path.
- `BrowserSession.close()` drops `cleanup=` — there are no capture files left to
  remove. `launch()` no longer takes a screenshot, so `SessionResult.screenshot`
  is gone.
- Driver contract: abstract `screenshot_bytes(page) -> bytes` replaces
  `screenshot(page, path)`, and
  `download_bytes(page, trigger, timeout_ms) -> BytesResult` replaces
  `expect_download(page, trigger, output)`. A backend whose API can
  only write a file spools it to a temporary directory and removes it before
  returning: nodriver does that for a capture, and the Playwright family reads
  back and deletes the download Playwright spools for it. nodriver still does
  not implement downloads.
- `results.PathResult` is gone with the paths it carried.
- `llm_browser.paths.prepare_output_path` is gone; the CLI owns the one copy.
- `llm-browser download --path` is optional and defaults to the filename the
  server suggested. Every path the CLI reports is absolute.
- `--out-dir` and `--capture-dir` are boundaries, not prefixes. A step `path:`
  is templated from `--data` and a download's filename comes from the server,
  so both are untrusted: a target that resolves outside its directory fails the
  command with nothing written, and a download's fallback name is reduced to
  its basename.
- `BytesResult.content` and `FlowError.screenshot` decode the base64 they
  serialize, so `model_validate(model_dump(mode="json"))` returns the bytes
  that went in. (`pydantic.Base64Bytes` would have been the obvious type and is
  the wrong one: it decodes on *construction* too, silently turning a real PNG
  into a few bytes of garbage.) A caller still passing a path string where the
  screenshot goes now gets a `ValidationError` instead of silence.
- `Driver.download_bytes` takes the step's `timeout` and passes it to the wait
  for the download, which previously always used Playwright's 30s default. A
  download that starts and then fails comes back as a `FlowError` rather than
  unwinding Playwright's own exception out of `run_flow`.

### Migration

- A step's `path:` still works — under `llm-browser run`, relative to
  `--out-dir`. A Python caller that relied on the runner writing it reads
  `FlowSuccess.outputs[step]` instead: `BytesResult` for `screenshot` and
  `download`, rows for `read` and `parse`, text for `dom`.
- Reading `FlowError.screenshot` / `.dom` as paths → they are the bytes and the
  text. `Path(err.screenshot).read_bytes()` becomes `err.screenshot`.
  `llm-browser run` still reports both as paths to the same files — but as
  *absolute* paths now, so a script that compared them against the relative
  value it passed in, or that `cd`s before reading, needs updating.
- `llm-browser run` now writes a `screenshot` or `download` that declared **no**
  `path:` into `--out-dir` (default: the CWD), under the name its payload came
  with. Previously a `screenshot` without a `path:` went to the session dir and
  a `download` could not run without one, so a CLI consumer gains files in its
  working directory unless it passes `--out-dir`.
- `llm-browser download` prints `name` and `bytes` alongside `path`. Anything
  `jq`-ing that command for `.path` is unaffected; anything asserting on the
  whole object is not.
- `session.take_screenshot()` → `Path(...).write_bytes(session.screenshot_bytes())`
- `session.save_screenshot(p)` → `p.write_bytes(session.screenshot_bytes())`
- `session.take_dom_snapshot()` → `p.write_text(session.dom_snapshot())`
- `session.download_file(sel, out)` → `p.write_bytes(session.download_file(sel).content)`
- `session.close(cleanup=True)` → `session.close()`
- A custom driver implements `screenshot_bytes` and `download_bytes` rather than
  `screenshot` and `expect_download`.

## 0.8.0 — 2026-09-09

### Added

- `BrowserSession.wait_for_element(selector, state=, timeout=, interval=, settle=)`, the `wait_for` flow step and the `llm-browser wait-for` CLI command — the one wait for `attached`/`detached`/`visible`/`hidden`/`stable` (text unchanged for `settle` ms), backed by `Driver.is_visible(locator)`; `find`, `find_all`, `frame` and `element_exists` all go through it.
- `FlowError.outputs` — outputs collected before a failing step (including inside a sub-flow) are no longer thrown away.
- `BrowserSession.screenshot_bytes()`, `save_screenshot(path)` and `scroll(dx, dy)`; `Driver.screenshot_bytes` has a non-abstract default.
- `llm_browser.flow_repository` (`FlowRepository` protocol, `FileFlowRepository`, `DictFlowRepository`, `LayeredFlowRepository`), `flow_pipeline.resolve_flow`/`resolve_flow_text` and `flows.load_flow_document(document, *, selector_map=None)` — the reference-resolution and validation stages split out of the old loader.
- `RunFlowStep.flow` accepts an inline child flow (`SubFlow`), so a flow needs no repository when its children are embedded; `flows.with_flow_path(result, path)`.
- `behavior.paced(behavior, runtime)` — brackets one interaction with its gap and post-action pause; nested scopes defer to the outermost one.
- `Driver.press` / `BrowserSession.press` accept a chord on nodriver (`Control+a`, `Shift+Tab`); the modifiers get their own key events around the key.
- `BrowserSession.scroll(dx, dy, selector=None)` and `Driver.scroll(page, dx, dy, locator=None)` — name the element when the thing you mean to scroll is not the document.
- Packaged Claude Code skill for authoring flows (`llm-browser skill install [--dest DIR] [--force]`, `llm-browser skill show`), plus `FLOWS.md`, `FLOW_PATTERNS.md` and `DRIVERS.md` reference docs shipped in the wheel.

### Changed

- `load_flow_text` raises `ValueError("invalid flow yaml: ...")` instead of leaking `yaml.YAMLError`; `run`/`validate` resolve their flow through `cli.resolve_flow_options` under `asyncio.run`, and an empty `--flow ''` is now a usage error.
- `Driver`'s class docstring is now the five-rule driver contract; `DriverHandle`, `DriverNotInstalledError`, `load_optional_module` moved to `llm_browser.drivers.handle` (still re-exported from `llm_browser.drivers`); `_resolve_with_fallback` probes the primary branch with the now non-waiting `count`.
- `BrowserSession` owns input: `click`, `fill`, `type`, `press`, `select_option` and `set_checked` each wait for the element, apply `Behavior` pacing and pick the humanized or plain driver primitive; `actions.py`, `steps.py` and `flows.py` no longer touch `session.driver`.
- `BehaviorRuntime` is reachable as `session.behavior_runtime` (was `session._behavior_runtime`); `behavior.paced` replaces the `enforce_gap` / `post_pause` / `mark_action_done` sequence callers spelled out.

### Breaking

- nodriver screenshots are PNG. They were JPEG bytes written into a file named `.png` — `FlowError.screenshot`, `take_screenshot()` and `screenshot_bytes()` all change format.
- `select` on something that is not a `<select>` raises `ValueError` before reaching the driver, so it comes back as a `FlowError` (and an `optional:` step can swallow it) instead of the driver's own exception unwinding out of `run_flow`. A `<label>` is resolved to the control it labels first, so a target the Playwright family accepted still works.
- nodriver's `select_option` sets the value through the select rather than clicking the `<option>`, matches a value **or** a label like Playwright, and refuses a disabled option, a disabled `<optgroup>` and a disabled `<select>` with a message naming which.
- nodriver activates the tab it drives in `goto` and before a capture. A tab Chromium has backgrounded has throttled timers and stalls `Page.captureScreenshot`, so any session that had opened a second tab was reading half-rendered pages.
- `Driver.count(locator)` and `Driver.text_content(locator)` never wait — they answer "right now"; on nodriver, `count`/`find_all` no longer block up to 10s for a late element.
- `flows.load_flow_text(text)` drops `subflow_loader`, `subflows`, `base_dir` and `selector_map`; validation itself takes no context at all.
- `RunFlowStep.flow` is now `SubFlow | str`; `RunFlowStep.subflow` is gone — the child lives in `flow`.
- `BrowserSession.goto` / `launch` / `launch_detached` reject non-`http(s)` URLs by default; pass `allowed_schemes=` to opt back in.
- `run-flow` references are resolved by a `FlowRepository` (`flow_pipeline.resolve_flow`) before validation, so a flow loaded from text no longer resolves siblings from the filesystem; an unknown selector `ref:` raises `ValueError` instead of pydantic `ValidationError`, and a missing flow file raises `FlowNotFoundError` instead of `FileNotFoundError`.

### Removed

- `wait` step, `BrowserSession.wait_until_stable`, `Driver.wait_for_stable_text`, `Driver.wait_for_state`, `Driver.count_now`.
- `llm_browser.flow_files` (`load_flow`, `run_flow_file`), `llm_browser.subflows` (`subflow_source`); `flow_pipeline.FlowSource`, `build_flow`, `subflow_refs`, `run_flow_ref`, `parse_flow_document`, the `SubflowLoader` alias; `SelectorMap` moved to `llm_browser.selector_map`.

### Fixed

- `read` / `parse` steps with a `path:` dump rows in JSON mode, so a schema declaring `Decimal`, `date` or `datetime` no longer kills the flow on its own output; a row that still cannot be written fails the step, naming the file.
- nodriver: `evaluate` invokes a script that is a function literal instead of evaluating it — `session.dom` returned nothing and `human_needed` never fired; `extract_rows` reads each row inside that row rather than answering every row with the page's first match; `click` scrolls its target into view; `is_visible` honours `visibility: hidden` via `checkVisibility`; typing emits a real `keyDown`/`keyUp` per character rather than `char` alone, which fired no keydown at all.
- camoufox: `scroll` parks the cursor over the content before turning the wheel — Gecko delivers a wheel event to whatever is under the pointer, and Playwright's starts off the page, so the scroll was a silent no-op.
- `launch_detached` records the pid before attaching and kills the browser it spawned if the attach fails, so a failed attach leaves neither an unrecorded Chromium nor a stranded earlier session.
- A YAML schema's `type:` string is parsed against an allowlist (`schema_types.resolve_type`) instead of `eval`-ed against `typing`.

### Migration

- `wait` step → `wait_for` with `state: stable` (`quiet_ms`→`settle`, `timeout_s`→`timeout` ms)
- `session.wait_for` → `wait_for_element`
- `load_flow` / `load_flow_text(subflows=…)` → `resolve_flow` + `load_flow_document`
- `count` no longer waits on nodriver — use `wait_for_element` instead
- `goto` accepts `http`/`https` only by default — pass `allowed_schemes=` to opt out
- `Driver.wait_for_state`, `count_now` and `wait_for_stable_text` are removed with no replacement

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
