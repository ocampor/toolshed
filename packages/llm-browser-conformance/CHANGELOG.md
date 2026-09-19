# Changelog

## 0.12.0 — 2026-09-18

Tracks `llm-browser` 0.20.0.

### Added

- `checks/input_steps.py`: nine input-step scenarios, each run under `Behavior.off()` and `Behavior.human()`, on `site/prefilled-autocomplete.html`, `site/fill-does-not-stick.html` and `site/hidden-checkbox.html` (ocampor/browser-api#68).

### Fixed

- `option:read` is covered: `flows/option-fields.yaml` carries a `read:` block.

## 0.11.2 — 2026-09-17

Tracks `llm-browser` 0.18.4.

### Added

- `read exclude`, on `site/read-exclude.html` and `flows/read-exclude.yaml`:
  the excluded text is gone, the read is on a detached copy (so `innerText`
  reads like `textContent`), and `value` still answers off the live element.

## 0.11.1 — 2026-09-16

Tracks `llm-browser` 0.18.3.

### Added

- Six `wait_for` text scenarios on `site/text-wait.html`: the text arriving,
  the text going, a `display:none` scope reading as absent (the
  `display: contents` wrapper it buries included), a
  `display: contents` scope reading its children, `text_present` answering in
  one read, and `flows/wait-text.yaml` for `text:` with `exact: true`. The
  `display: contents` wrapper holds text of its own, and `flows/wait-text.yaml`
  gates its read on `when: text_present`.
- `text_present` joins the `when:` conditions `docs/coverage.md` requires a
  scenario for.

## 0.11.0 — 2026-09-16

Tracks `llm-browser` 0.18.0.

### Added

- `dom first match`: `dom("main, article, body")` on `site/body-fragment.html`
  reads the `<body>` that wraps the `<main>`, pinning "first in document
  order" rather than first in the selector list.

## 0.10.1 — 2026-09-15

Tracks `llm-browser` 0.17.1.

### Changed

- `patchright` pinned to `1.62.*`, matching `llm-browser`'s `>=1.62.3,<1.63`.

## 0.10.0 — 2026-09-15

### Added

- Seven `popup and new-tab download` scenarios on `site/popup-download.html`:
  same-tab attachment, popup to inline pdf, popup to attachment, blank link to
  a file, blank form post, popup renders then fetches, popup with no file.
- `flows/popup-download.yaml`: one `download` step aimed at a `{{ selector }}`.
- `site/popup-then-download.html`, the popup that commits a document before it
  fetches the file — the shape behind gap #40.
- `/billtax/print.action` and `/billtax/attach.action` (302s), plus
  `/billtax/downloadFile.action` and `/attach.pdf` (`site/receipt.pdf` under an
  `inline` or `attachment` `Content-Disposition`).
- `--headed` runs the suite in a visible browser instead of headless.
- `known_gaps` for #40: `popup renders then fetches` on patchright and
  camoufox, `popup to inline pdf` and `blank form post` on camoufox.

### Fixed

- `close_tab` no longer fails the cleanup when the tab closed itself, and
  `close_opened_tabs` accepts `opened=None` where no tab is guaranteed.

## 0.9.0 — 2026-09-13

Tracks `llm-browser` 0.17.0.

### Changed

- `read properties` also reads a bare `read` (no `extract:`), so the default
  `text` field is checked in a real browser.

## 0.8.0 — 2026-09-13

Tracks `llm-browser` 0.16.0.

### Added

- `wait enabled`, `wait aria-disabled` and `fill waits for enabled` scenarios on
  `site/unlock-input.html`: an input and an `aria-disabled` button that unlock
  after the checkbox, claiming `field:wait_for.state`.
- `repeat a step` and `repeat a sub-flow` scenarios on `site/repeat-list.html`,
  claiming `option:repeat`.
- `skipped steps` scenario: `flows/option-skipped.yaml` runs a `when:` miss and
  an `optional:` miss, claiming the new `api:skipped` key.
- `sticky bands` scenario: `site/sticky-bands.html` covers the top and bottom of
  the viewport, recording per driver whether a plain click reaches the middle.

## 0.7.0 — 2026-09-13

Tracks `llm-browser` 0.15.0.

### Added

- `jittered key delay` scenario: `flows/type-delay-jitter.yaml` types with
  `delay: [40, 80]` and `humanize: true`, claiming `field:type.humanize` and
  `api:type.delay_jitter`.
- `humanized click and fill` scenario: `flows/humanize.yaml` checks the
  curved-path click and the key-by-key fill still arrive as trusted input,
  claiming `field:click.humanize` and `field:fill.humanize`.

## 0.6.0 — 2026-09-13

Tracks `llm-browser` 0.14.0.

### Added

- `explore a list` scenario, claiming `session:explore`.
- `explore a button` scenario on `explore-actionability.html`: a button under a
  sticky banner and a disabled one, for the verdict, `why_not` and `covered_by`
  a `count` cannot answer.
- `explore a click cost` scenario on the same page: below the fold, a label
  and its own checkbox, a `<fieldset>`-disabled input, a box of no size and a
  card that swallows a dismiss button.
- `explore many` scenario asserts a target the page cannot parse answers
  `error: not css` without costing the batch its other answers.
- `survey a page` scenario asserts a landmark's `count` is page-wide (two
  elements answer to `[aria-label="Pager"]`) and that nothing was `truncated`.

## 0.5.0 — 2026-09-13

Tracks `llm-browser` 0.13.0.

### Added

- `dom body` scenario: `site/body-fragment.html` plus `flows/dom-body.yaml` —
  the `<body>` outerHTML lxml refused, at two `level`s; it claims
  `field:dom.level`.
- `read properties` scenario: `innerText`, `tagName` and `childElementCount`
  read off the same rows as an `href` attribute.

## 0.4.0 — 2026-09-11

Tracks `llm-browser` 0.11.0.

### Removed

- `solve captcha` scenario, the `site/captcha.html` fixture and
  `flows/solve-captcha.yaml` — `llm-browser` dropped the `solve_captcha` step.
  The element-`screenshot` scenario stays.

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
