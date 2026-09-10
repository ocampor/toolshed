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
uv run llm-browser-check --json                # machine-readable, for agents
uv run llm-browser-check --delay 2500          # slower machine, slower fixtures
```

Exit code is non-zero if any scenario **failed** — or if a known gap has
**closed**, because a stale gap table is a lie about what the drivers do.

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

### Pinned driver versions

`pyproject.toml` pins `patchright`, `camoufox` and `nodriver` to the minors in
`packages/llm-browser/uv.lock`. The suite exists to say whether *your change*
broke a driver, and it cannot do that while a driver upgrade is drifting
underneath it — a fresh resolution of `nodriver>=0.40` picked up 0.50, whose
CDP internals llm-browser's driver does not speak, and every failure would
have been misattributed. Bump the pins together with llm-browser's lock.

camoufox is launched with `humanize=False` (see
`llm_browser_conformance.drivers.configured`). Its humanized cursor
intermittently leaves a Playwright `click` waiting out the whole 30s action
timeout on a target it has already declared visible, enabled and stable —
a Camoufox cursor problem, not an llm-browser contract question, and one
flaky scenario poisons every answer in the column.

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
    Scenario("my thing", Section.STEPS, a_thing_that_must_hold, "my-page.html"),
]
```

Add the module's `SCENARIOS` to `ALL_SCENARIOS` in `scenarios.py` and both
front ends pick it up: a row in the table and a pytest case. A check may
return a one-line string, which lands in the details — used where drivers
legitimately differ and the point is to *record* which behaviour this one has
(`disabled button`, `new tab`) rather than force one answer.

## Turning a real failure into a fixture

The suite is meant to grow out of production failures. The recipe:

1. **Capture the page.** From a live session:
   `llm-browser dom --selector body --level low` plus a screenshot; from a
   failed flow, the `dom` and `screenshot` paths already on the `FlowError`.
2. **Strip it to the minimum that still reproduces.** Keep the element(s),
   the CSS that governs their visibility and layout, and the JS that mutates
   them. Replace every external script with a few inline lines that mimic the
   timing (`setTimeout`, driven by `?delay=`). No external requests, no
   secrets, no real content, no analytics — the page must be self-contained
   and under ~100 lines.
3. **Paste in the isTrusted recorder** (the snippet above), so the new page
   can answer trust questions like every other one.
4. **Name it after the failure mode**, not the site:
   `overlay-intercepts-click.html`. Add a flow under
   `src/llm_browser_conformance/flows/` reproducing the original steps, and a
   scenario asserting the behaviour you *want* — the fix's behaviour. Until
   the library is fixed, list it in `known_gaps` (`xfail(strict=True)` under
   pytest) so the suite documents the gap instead of hiding it.
5. **Run it:** `uv run llm-browser-check --driver <the one that failed>`.
6. **Cite the origin** in a one-line HTML comment at the top of the page —
   site and date only, no URL parameters, no identifying data.

## Known gaps

Every `xfail` in the current run, i.e. behaviour the suite says should hold
and does not. `llm-browser-check --json` can be diffed against this table:
each entry corresponds to a result whose `outcome` is `xfail`, and an `xpass`
means a row here is out of date.

| scenario | driver | gap |
| --- | --- | --- |
| custom select rejects select | patchright, camoufox, nodriver | `select` on a non-`<select>` raises out of `run_flow` instead of returning a `FlowError`: `execute_action` only converts `TimeoutError` and `ValueError` into an `ErrorResult`, so `optional:` cannot swallow it and the CLI cannot report it |
| dispatch is untrusted | camoufox | Gecko marks an event dispatched from Playwright's chrome-privileged agent as trusted, so `dispatch=True` is indistinguishable from real input on Firefox |
| flow failure flags a login wall | nodriver | `page_probe.js` is a function literal and nodriver's `evaluate` runs it as an expression, so `PageProbe` comes back empty and `human_needed` is always `False` |
| visibility:hidden is hidden | nodriver | `is_visible` tests `offsetParent`/`getClientRects`, neither of which notices `visibility:hidden` |
| select_option | nodriver | `select_option` native-clicks the `<option>`; a closed native select ignores it and the value never changes |
| native select optgroup | nodriver | `select_option` native-clicks the `<option>`; a closed native select ignores it and the value never changes |
| native select disabled option | nodriver | clicking a disabled `<option>` is a no-op, so the step reports success instead of failing |
| typing fires trusted keydown | nodriver | `send_keys` dispatches `Input.dispatchKeyEvent type=char`, which fires `keypress`/`input` but no `keydown` |
| sticky header | nodriver | `click` does not scroll the target into view, so the CDP mouse event is dispatched at viewport coordinates the button is not at and nothing is clicked |
| slow xhr rows | nodriver | `extract_rows` walks rows from Python and `NodriverDriver.all()` drops the selector, so `child()` re-queries the whole document and every row reads the first match |

Not gaps — unimplemented APIs, reported as `skip`:

| scenario | driver | reason |
| --- | --- | --- |
| iframe click, iframe form | nodriver | `enter_frame` is not implemented |
| download | nodriver | `expect_download` is not implemented |
| shadow dom | nodriver | selectors do not pierce an open shadow root |
