# Changelog

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
- Coverage follows the session API: `session:dom_snapshot` in,
  `session:take_screenshot`, `session:save_screenshot` and
  `session:take_dom_snapshot` out.

### Added

- `outputs json dump` (`api:outputs.json`): `outputs` holds real bytes for a
  Python caller, and `model_dump(mode="json")` base64-encodes them rather than
  crashing the serializer.

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
