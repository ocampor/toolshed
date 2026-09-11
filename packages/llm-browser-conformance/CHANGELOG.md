# Changelog

## Unreleased

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
