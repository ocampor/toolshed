# llm-browser-conformance

A real-browser conformance suite for [`llm-browser`](../llm-browser) drivers.

It answers two questions:

1. **Did my change break a driver?** Run it after touching anything below
   `BrowserSession` and read one table with every driver's answer to every
   question.
2. **Does my new driver hold to the contract?** Implement
   `llm_browser.drivers.base.Driver`, run the suite against it, and the gaps
   are named for you.

Everything is self-served. The pages under `src/llm_browser_conformance/site/`
are served by a throwaway `http.server` on a random loopback port, so a run is
reproducible on a laptop, in CI and inside a sandbox — no public URLs, no
network, no third-party site changing under you.

## Running it

```bash
cd packages/llm-browser-conformance
uv sync --all-extras          # patchright, camoufox and nodriver
uv run patchright install chromium
uv run python -m camoufox fetch          # only for the camoufox driver
```

nodriver drives a real Chrome over CDP and ships no browser: it needs
`google-chrome`, `google-chrome-stable`, `chromium` or `chromium-browser` on
`PATH`, and skips with that exact reason if none is there.

```bash
uv run llm-browser-check                       # every installed driver
uv run llm-browser-check --driver nodriver     # one driver; repeatable
uv run llm-browser-check --only "wait" --only "iframe"   # substring filter
uv run llm-browser-check --failed              # just what broke last run

uv run llm-browser-check --json                # machine-readable, for agents
uv run llm-browser-check --delay 2500          # slower machine, slower fixtures
```

Exit code is non-zero if any scenario **failed** — or if a known gap has
**closed**, because a stale gap table is a lie about what the drivers do.

Every run merges its outcomes into `.llm-browser-check/last.json`, which
`--failed` rereads to pick only the scenarios that failed or xfailed, per
driver. The path is **relative to the working directory**, so run `--failed`
from wherever you ran the suite; a record this build cannot parse is ignored
with a warning rather than failing the run. The directory is gitignored here —
add `.llm-browser-check/` to your own `.gitignore` if you run the suite in
another project.

The same scenarios also run under pytest, gated so the normal run stays fast
and browser-free:

```bash
uv run pytest -q                    # everything skipped, no browser launched
uv run pytest --real -q             # the real thing
uv run pytest --real --driver nodriver -q -k "iframe"
```

Prefer pytest when you want a full assertion traceback; prefer
`llm-browser-check` when you want the table.

### Reading the table

| cell    | meaning |
| ------- | ------- |
| `pass`  | the scenario held, with its wall-clock cost |
| `xfail` | a **known gap** for that driver: it failed, and the reason is in the details below the table |
| `XPASS` | a known gap has closed — fix the table, this is a failure |
| `skip`  | the driver has no API for what the scenario needs (`enter_frame`, `expect_download`), or the driver is not installed |
| `FAIL`  | a real regression |
| `-`     | the scenario does not apply to that driver (the stealth rows are nodriver-only) |

### How the drivers are configured

Two decisions, each documented where it is made:

- **Pinned versions.** `pyproject.toml` pins `patchright`, `camoufox` and
  `nodriver` to the minors in `packages/llm-browser/uv.lock` — the comment
  above the pin says why. Bump them together with that lock.
- **camoufox runs with `humanize=False`**, and Playwright's own action timeout
  is capped: see `llm_browser_conformance.drivers.configured` and
  `bound_action_timeout` for the reasoning.

## The fixture site

One page per behaviour, plain HTML plus a few lines of inline JS. Two
conventions:

**Timing comes from `?delay=`** (default 1500, the suite passes 1000):

```js
const delay = Number(new URLSearchParams(location.search).get("delay") ?? 1500);
```

**Every page carries the isTrusted recorder.** Driver rule 2 says input must
be trusted events — OS-level or CDP `Input.*`, never synthetic DOM events —
and the only honest way to check that is to ask the page:

```js
const recordTrust = (e) => {
  if (e.target.setAttribute) e.target.setAttribute("data-trusted", String(e.isTrusted));
};
document.addEventListener("click", recordTrust, true);
document.addEventListener("keydown", recordTrust, true);
```

`form.html` adds a third listener writing `data-trusted-input` for `input`
events, because a driver can deliver a trusted value without ever emitting a
keydown — and a page that watches keystrokes (masks, autocompletes, hotkeys)
will not react to it. `Context.trusted(selector, attribute)` reads either.

## The stealth counter

Driver rule 3 says JS runs in `evaluate`, `is_visible`, `input_value` and
`extract_rows` and nowhere else, so a detector fingerprinting CDP Runtime
traffic sees nothing on the common path. That is only checkable on a driver
that speaks CDP itself, so the two `[stealth]` scenarios are nodriver-only.

`checks/stealth.py` hooks nodriver's `Transaction`, which it builds for every
outgoing command, and records the method name. `attached` must send **zero**
`Runtime.*` calls (it polls `count`, a plain `DOM.querySelectorAll`);
`visible` may send **at most one per poll** (it has no CDP predicate, so it
pays one `Runtime.callFunctionOn`), and the poll count is measured by wrapping
`driver.is_visible` rather than guessed from the clock.

## Adding a driver

1. Implement `llm_browser.drivers.base.Driver` and register it (see
   `llm_browser/drivers/__init__.py`).
2. Add its name to `CONFORMANCE_DRIVERS` in
   `src/llm_browser_conformance/drivers.py`, and give `unavailable()` the
   reason it might not be runnable here (missing extra, missing binary).
3. `uv run llm-browser-check --driver <name>`.
4. Every `FAIL` is a contract violation to fix. Something the driver
   deliberately does not implement should `raise NotImplementedError` so the
   scenario reports `skip` with your message, not `FAIL`. Something it does
   differently on purpose gets a `known_gaps` entry naming the reason.

## Adding a scenario

A scenario is data. Write the check, then register it:

```python
def a_thing_that_must_hold(ctx: Context) -> None:
    outputs = expect_success(ctx, "my-page.html", "my-flow")
    assert one_text(outputs, "result") == "clicked"


SCENARIOS = [
    Scenario("my thing", Section.STEPS, a_thing_that_must_hold),
]
```

Add the module's `SCENARIOS` to `ALL_SCENARIOS` in `scenarios.py` and both
front ends pick it up: a row in the table and a pytest case — both go through
`run_scenario`, so they cannot disagree about the same run. A check may
return a one-line string, which lands in the details — used where drivers
legitimately differ and the point is to *record* which behaviour this one has
(`disabled button`, `new tab`) rather than force one answer.

## Coverage

[`docs/coverage.md`](docs/coverage.md) — every step type, step field, step
option, `when:` condition and `BrowserSession` method the library exposes, and
the scenario that exercises it. The rows are *introspected* from
`llm_browser.models` and `llm_browser.session`, so a step type or a field
added to the library shows up uncovered and `tests/test_coverage.py` fails
until a scenario claims it. That is what makes a green run an acceptance test
for a release rather than a spot check.

A scenario claims what it exercises through `covers`:

```python
Scenario(
    "goto wait_until",
    Section.STEPS,
    goto_waits_for_the_load_state_it_was_asked_for,
    covers=frozenset({"step:goto", "field:goto.wait_until"}),
)
```

Regenerate the table with `llm-browser-check --coverage > docs/coverage.md`.

## Known gaps

[`docs/known-gaps.md`](docs/known-gaps.md) — generated from the `known_gaps`
entries in `checks/`, regenerated with `llm-browser-check --gaps`, and checked
against the code by `tests/test_docs.py` so it cannot drift.

An unimplemented API is not a gap: it raises `NotImplementedError` and the
scenario reports `skip` with the driver's own message.

## Growing the suite

[`docs/fixtures.md`](docs/fixtures.md) — how to turn a production failure into
a fixture page, a flow and a scenario.
