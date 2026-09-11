# Changelog

## 0.3.0 — 2026-09-11

Tracks `llm-browser` 0.10.0.

### Added

- `solve captcha` scenario: `site/captcha.html` plus `flows/solve-captcha.yaml`
  drive a whole image captcha — a wrong answer, the page's error left on screen,
  a fresh crop, the right answer — against a stub reader put on
  the session as `captcha_reader`, and assert the crop is smaller than the page.
- `screenshot step` also claims `field:screenshot.selector`, asserting the
  element capture is smaller than the page capture.

## 0.2.1 — 2026-09-10

### Fixed

- `launched_session` registers its browser with `interrupts` while live and
  unregisters it on a normal `close()`; an `atexit` hook and chained
  SIGINT/SIGTERM handlers close whatever is still registered.
- `close_stranded_sessions` pops and closes sessions one at a time, ignores a
  re-entrant call instead of restarting the sweep, and defers a
  `KeyboardInterrupt`/`SystemExit` raised mid-sweep until every session has
  had its turn.
- `install_interrupt_handlers` saves the previous SIGINT/SIGTERM handlers,
  chains to them after the sweep, restores them once no session is
  registered, and only installs from the main thread.
- `handle_interrupt` stays a no-op after chaining when the previous handler
  was `SIG_IGN`, instead of falling through to the default action.
- `LaunchPlaceholder` holds a registry slot across `session.launch()`, so a
  signal during launch no longer restores the handlers before the real
  session registers.
- `close_stranded_sessions` keeps the first `KeyboardInterrupt`/`SystemExit`
  seen across the sweep instead of the last.

## 0.2.0 — 2026-09-10

Tracks `llm-browser` 0.9.0, where the library stopped writing output files.

### Changed

- `download`, `screenshot`, `read`, `parse` and `dom` scenarios assert what
  comes back in `FlowSuccess.outputs` — a `BytesResult` for the first two —
  and that the step's `path:` left the filesystem alone. `path:` is an
  instruction to the CLI now, and a runner that honoured it would pass every
  assertion about the output while quietly putting the old design back.
- `flow failure captures artifacts` asserts PNG bytes and sanitized HTML text
  on `FlowError`, not two paths that exist.
- `support.wrote_nothing(ctx)` brackets a scenario body and fails if the
  session directory or the working directory gained or changed a file;
  `artifact_snapshot` moved there from `checks/session_api.py` to back it.
- `support.wrote_nothing` compares `(name, size, mtime_ns)` for the working
  directory as well as the session dir. Names alone could not see a run
  *overwriting* a file that was already there, which is the likeliest shape of
  the regression it guards, since flow `path:` values are relative names.
- Coverage follows the session API: `session:dom_snapshot` in,
  `session:take_screenshot`, `session:save_screenshot` and
  `session:take_dom_snapshot` out.

### Added

- `outputs json dump` (`api:outputs.json`): `outputs` holds real bytes for a
  Python caller, and `model_dump(mode="json")` base64-encodes them rather than
  crashing the serializer.
- A `[cli]` section, opened by `cli run writes outputs` and `cli run failure
  captures` (`api:cli.out_dir`, `api:cli.capture_dir`).
  They drive the installed `llm-browser` console script as a subprocess
  against the fixture site, because the other half of "the library writes
  nothing" — that `llm-browser run` puts the results where the flow and the
  flags asked — is only true of the command, and is exactly what an
  in-process check cannot see. They use `daemon` rather than `open`: a
  launched patchright session belongs to the process that launched it, so
  only the detached-over-CDP session survives to the next invocation.
  patchright only; what the CLI writes is decided above the driver, and a
  second browser per column would triple the cost of a run to re-check the
  same code.
- `cli run writes typed rows` (`api:cli.typed_rows`): a `parse` schema
  declaring `Decimal` and `date` reaches the CLI writer as those objects, and
  `json.dumps` can encode neither. The library used to write that file itself,
  in JSON mode; moving the write to the CLI reintroduced the crash once, and
  this is what catches it.
- `flow failure capture level` (`api:capture_level`): the failing page's DOM
  snapshot honours `BrowserSession(capture_level=)` — `medium` keeps the
  `href` the flow would have followed, `high` drops it. `never.html` gained an
  anchor nothing clicks, so a capture taken there has a link to keep or drop.

## 0.1.1 — 2026-09-10

### Added

- `llm-browser-check --failed` reruns only the scenarios that failed or
  xfailed last time, per driver — the drivers disagree about what is broken,
  and a scenario only camoufox got wrong is not worth relaunching Chrome for.
  Nothing to rerun is success and says so; nothing to rerun *from* is a usage
  error. No parallelism: the scenarios share one browser per driver.
- Every run merges its outcomes into `.llm-browser-check/last.json`, the file
  `--failed` rereads. The path is relative to the working directory, so run
  `--failed` from wherever the suite was run. It is gitignored in this repo;
  add `.llm-browser-check/` to your own `.gitignore` if you run the suite in
  another project. A record this build cannot parse — a renamed `Section`, an
  `Outcome` from a newer build, a rollback — is ignored with a warning rather
  than failing the run.
- Scenarios: `screenshot is a png`, `parse writes typed rows`, `dom snippet`,
  `key chord` and `scroll`, plus the `parse-rows.html` fixture and the
  `schemas/invoice.yaml` schema behind the first of them.

### Changed

- `runner.run` takes a plan (driver → scenarios) rather than a driver list and
  a scenario list, because `--failed` reruns a different set for each;
  `runner.full_plan(drivers, scenarios)` builds the every-driver case. The
  table orders its sections as they are declared, so a per-driver plan cannot
  shuffle them.
- Ten known gaps closed by the fixes in `llm-browser` 0.8.0 — see
  [`docs/known-gaps.md`](docs/known-gaps.md) for what is left. The camoufox
  `dispatch is untrusted` row now says it is not closable from this side.
- Coverage introspection reads `BrowserSession` off its MRO instead of
  `inspect.isfunction`, so a `property`, `cached_property` or `classmethod`
  the library grows is required like any other public member.
- Scenario renames, so every name is reachable on its own through `--only`:
  `scroll ticks` → `wheel ticks` (`scroll` selected both) and
  `templating miss` → `unresolved placeholder` (`templating` selected both).
- The tab scenarios close their popup through `tabs_closed_after`, which lets
  the scenario's own exception win: a cleanup that fails on the way out is
  attached to it with `add_note` instead of replacing it in the table. Run
  details carry an exception's notes whatever the verdict — a failure, a known
  gap and a skip all report them.
