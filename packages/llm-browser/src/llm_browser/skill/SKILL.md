---
name: llm-browser-flows
description: Author, debug and hand over llm-browser YAML flows for a specific site — use when asked to automate a web app, scrape a logged-in page, or fix a flow whose selector broke.
---

# Authoring llm-browser flows

Read the reference before writing YAML; this file is only the method. All three ship next to it:

- `reference/FLOWS.md` — the flow language: every action and its fields, `wait_for` states, `when` predicates, selector forms, step options, template vars, extract specs.
- `reference/FLOW_PATTERNS.md` — worked YAML for hard widgets, `--level` attribute table, `type` vs `fill`, and the migration table for retired spellings.
- `reference/DRIVERS.md` — per-driver selector and key support, stealth model, escape hatches.

Never restate a fact from those files here; link to it.

## Intake (ask once, all at once)

| Ask | Why | Default if unanswered |
|---|---|---|
| Entry URL and how you reach it | it is the session's only `goto` | the URL given, verbatim |
| Goal in one sentence | decides where the flow ends | "reach the screen and read it" |
| Expected outputs: which rows, which fields, what file | picks `read` vs `parse` vs `dom` vs `download` | `read` with an `extract` map, no `path:` |
| Where credentials live (1Password item, env var) — never the values | they become flow params | flow declares params; the caller supplies them |
| Selectors, ids or visible labels you already have | skips most reconnaissance | none; discover everything |
| Site traits: SPA, iframes, captcha, login wall, rotating ids, fraud-lockout sensitivity | drives waits, healing, pacing | SPA yes, rotating ids no, treat as lockout-sensitive |
| Never-click list (submit, pay, seal, delete, "Enviar") | those steps are never written | nothing irreversible; ask before any such button |
| Other domain rules (sequential-only, one record at a time, review-before-submit) | they become a comment block in every flow | none assumed; ask |
| Driver in use (`patchright`, `camoufox`, `nodriver`) | decides whether XPath and key chords are available at all | `patchright`, headed, attached |
| Existing flows directory and `selector_map.yaml` | new work extends them | `flows/<domain>/` and `flows/<domain>/selector_map.yaml` |

- State the defaults you assumed back to the user in one line before you start.
- Domain rules stay the consumer's: copy them verbatim into a comment block at the top of every flow file you write, never into the library.

## Reconnaissance, fastest path

- Attach to the browser the user is already in — it holds the warmed profile and the live login. Ask them to restart Chromium with `--remote-debugging-port=9222` if it is not listening yet.
- Only when nothing is running: start one through the project's own wrapper (a `just` recipe), so it gets the warmed `--profile`. A bare `daemon` starts a cold identity and re-triggers the login wall.
- **One page load per session.** After the entry `goto`, move by clicking. A second `goto` throws away SPA state and, on a site with fraud detection, can lock the account.
- Map region by region, and probe candidates with `find`, not with page-sized dumps. `find --all` returns each match's raw `outerHTML`, so `data-*` and `aria-*` are readable per candidate.

```bash
llm-browser attach --cdp-url http://localhost:9222
llm-browser --cdp-url http://localhost:9222 --target-id <target_id> goto --url https://portal.example.com/invoices
llm-browser --cdp-url http://localhost:9222 --target-id <target_id> dom --selector "main" --level xhigh --max-depth 3
llm-browser --cdp-url http://localhost:9222 --target-id <target_id> dom --selector "form#search" --level medium --max-depth 3
llm-browser --cdp-url http://localhost:9222 --target-id <target_id> find --selector "input[name='rfc']" --all
llm-browser --cdp-url http://localhost:9222 --target-id <target_id> screenshot
```

- Cold start instead of attaching: `llm-browser daemon --url https://portal.example.com --profile ./.browser-profile --executable /usr/bin/chromium`, the same `dom` / `find` commands without the `--cdp-url` / `--target-id` prefix, then `llm-browser stop`.
- Pick the `--level` from the table in FLOW_PATTERNS → Reading the page, in one shot. Stepping down through levels costs a page-sized read each time, and `medium` drops `role` and `placeholder` while `xhigh` keeps them.
- Read `count` from `find --all`: `1` is a selector, `0` is wrong, `> 1` needs narrowing. Same-text controls are the usual trap — three "Aceptar" buttons, one visible.
- Try the user's known ids first. Stop the moment one stable selector exists per target; do not enumerate the page.

## Selector rules (ranked)

| Rank | Form | Example | Driver |
|---|---|---|---|
| 1 | stable `id` | `selector: { id: "rfc" }` | any |
| 2 | `name` | `selector: "input[name='rfc']"` | any |
| 3 | `data-*` / `aria-label` | `selector: "[data-testid='submit-row']"` | any |
| 4 | label-anchored CSS | `selector: "div:has(> label[for='0168']) select"` | any |
| 5 | stable class or structural CSS | `selector: { css: "form#search input[type='date']" }` | any |
| 6 | label-anchored XPath | `selector: { xpath: "//label[contains(text(),'Copropiedad')]/following::select[1]" }` | patchright / camoufox only |
| 7 | XPath by button text | `selector: { xpath: "//button[normalize-space()='Buscar']" }` | patchright / camoufox only |

- **XPath is not portable.** On `nodriver` only real CSS reaches the page, so ranks 6-7 and Playwright's `:has-text(...)` fail there; fall back to rank 4 or to an id plus the prefix-healing pattern. Full support matrix: DRIVERS → Selector and key support.
- Never `nth-child` on a list: row order changes between loads and you silently read the wrong row.
- Never a generated or hashed class (`.css-1x2y3z`, `.jsx-8842`) — it changes every deploy.
- Never `#135textbox78`: an id starting with a digit is invalid CSS. Write `{ id: "135textbox78" }`.
- One fallback per map entry (`primary` / `fallback`); a deeper chain hides which branch matched.
- Group refs by page area (`login.*`, `search.*`, `results.*`) so the map reads like the screen.
- Keep templated selectors (`{{ }}` inside a selector) inline in the flow; map entries name constants.
- Prefer a label-anchored selector to a rotating id — labels do not rotate, so nothing needs healing. Where no label exists, keep the id and heal the prefix (FLOW_PATTERNS → Rotating-prefix ids). Healing is a consumer-side, one-shot, auditable rewrite — never re-infer selectors per call.
- **Detect rotating ids without a second load** on a lockout-sensitive site: compare the ids you recorded in the last run's notes against today's. Two loads in a fresh tab are fine only where the intake said fraud lockout is not a concern.

## Waits

- After every navigation and every XHR-triggering click, add a `wait_for` step with the cheapest state that proves the transition happened. A `wait_after:` sleep is never the answer — it is either too short (flaky) or too long (slow), and it fails silently.

| Transition | `state` | Selector to wait on |
|---|---|---|
| New page or new screen rendered | `attached` | an element only the destination has |
| Modal, overlay or row removed | `detached` | the backdrop / dialog root |
| Element revealed by a CSS toggle (already in the DOM) | `visible` | the revealed element |
| Spinner or overlay hidden by a CSS toggle | `hidden` | the spinner |
| A value finished recalculating or streaming | `stable` | the element holding the value |

- `visible` / `hidden` only when CSS toggles the element; on a DOM swap they are a slower `attached` / `detached`.
- `timeout` = 3× the latency you actually observed, minimum 3000. State semantics and the `settle` / `interval` rules: FLOWS → Waiting.
- `optional: true` for anything dismissable, so a missing banner is a skip and not a failure. It is for variant page state, never for "this might flake".
- Branch on presence with `when` rather than a wait you expect to fail.

## Flow structure

- One flow per screen — or per atomic intent when a human has to act mid-screen. Splitting `fill` / `submit` / `confirm` into separate files is what lets the handoff land between them.
- One flow per optional field, so a caller can run only the fields a probe step said were missing.
- Compose with `run-flow`; children are **leaf-only**. A `flow:` reference resolves relative to the parent flow's own directory; a `schema_path:` is CWD-relative or absolute.
- Declare every input in `params:` and use `{{ name }}` in string values; see FLOWS → Structure for the optional-param spelling.
- Branch in the parent, not the child: `when:` on the `run-flow` step keeps typed booleans and nulls intact, which templating a child's `data:` block cannot.
- Write `when:` predicates exactly as FLOWS → Conditions spells them; `{ field: X, op: eq, value: V }` needs its `value:` key, and a missing one is a `KeyError` mid-run, not a load-time error. `element_missing` is the idempotent-toggle guard.
- `recovery_*` flows: one per known dead end, named for what it undoes (`recovery_dismiss_modal.yaml`, `recovery_session_timeout.yaml`). Keep them idempotent, run them before retrying the failed step, and reference the same file from the happy path as an `optional: true` `run-flow` step.
- Outputs: `read` + `extract` for rows and fields, `parse` + `schema_path` for typed rows, `dom` for a snapshot, `download` for files. Every result comes back in `FlowSuccess.outputs`; the runner writes nothing. `path:` is an instruction to `llm-browser run`, which writes that file under `--out-dir` — a Python caller gets the value and decides. A `screenshot` or `download` with no `path:` is still written under `--out-dir`, under the name its payload came with; `read`/`parse`/`dom` without one stay inline in the JSON.
- Secrets are params, never literals: `value: "{{ password }}"`, supplied via `--data`, fetched and used in one shell command so the value never reaches tool output. From Python, `run_flow(..., redact=[password])` replaces it with `***` in outputs, logs, errors and retry hints.
- Failure capture is automatic: `BrowserSession(capture="screenshot" | "dom" | "both" | "none")`. `FlowError` carries `step`, `screenshot` (PNG bytes) and `dom` (HTML text) in memory, the `outputs` collected so far, and a `retry_hint` naming the failed step. `llm-browser run` writes those two to `--capture-dir` (default: the session dir). `--capture-level` (`low`/`medium`/`high`/`xhigh`, default `high`) decides how hard the DOM snapshot is sanitized — reach for `medium` when you need the `href` the page would have followed.
- `FlowError.human_needed` true means a password prompt, a live captcha or an interstitial — retrying is useless. Tell the user which screen it is, that they must log in or clear the challenge in the attached browser, and the exact `run --from <step>` to resume with.
- There is no in-flow pause. A flow that needs a human ends before the human's step; the caller prints the instruction and is re-invoked afterwards against the same session.
- An *image* captcha is the one challenge a flow can answer itself: `solve_captcha` crops the image and hands the PNG to the reading function the host process gave the session as `BrowserSession(captcha_reader=...)` — the library never reads it, and the CLI passes none, so from the command line this step always asks for a human. With no reader, or `retries` exhausted, it fails with `human_needed` and the paragraph above applies. It is not for reCAPTCHA or Turnstile: those are widgets, not pictures, and still need the person. See FLOWS → Captchas.

## Anti-detection

- Pacing is the driver's job: `--behavior-config <file>` jitters keystrokes, clicks and pauses on every input. A fixed cadence is itself a fingerprint; do not hand-roll sleeps in its place.
- `dispatch: true` is a last resort for a JS-bound submit handler that ignores a real click. It emits `isTrusted=false` on every driver — camoufox included — so it is never the safer path. Details: DRIVERS → Anti-bot landscape.
- One page load per session; no deep links into inner pages. If a page cannot be reached by clicking, stop and ask the user to open it, then run the flow against the page they opened.
- Sensitive sites (banking, tax, anything with fraud lockout): headed, attached to a warmed real profile, `camoufox` if it must be headless, no parallel sessions against one account, and no retry loop on a login step — a second failure means stop and ask.
- Never-click enforcement: do not write the step. Leave a comment naming the forbidden control so the omission reads as deliberate.

```yaml
# never-click: #btnSellar ("Sellar") — timbrado is irreversible; the human presses it.
```

## No JavaScript in flows

- Do not write `eval:` steps. Every common reason to reach for one has a JS-free answer in FLOW_PATTERNS; if a page still needs JS, that is a missing primitive and belongs upstream in llm-browser. Report it, do not patch around it.

## Library gaps

Report these to the user rather than working around them.

| Gap | Consequence |
|---|---|
| No in-flow human pause — `checkpoint:` is not a field and is silently dropped | split the flow and re-invoke after the human acts |
| `check` cannot target a visually hidden input | needs a clickable label or a state class to gate on |
| No `resume` command | `run --from <step>` against the still-open session is the only re-entry |
| XPath and key chords are unavailable on `nodriver`, and a chord types its literal text and reports success | see DRIVERS → Selector and key support before choosing a driver |

## Iterate loop

```bash
llm-browser validate --flow flows/search.yaml --selector-map flows/selector_map.yaml
llm-browser run --flow flows/search.yaml --selector-map flows/selector_map.yaml --data '{"rfc":"XAXX010101000"}'
llm-browser run --flow flows/search.yaml --selector-map flows/selector_map.yaml --data '{"rfc":"XAXX010101000"}' --from "results appear"
```

1. `validate` first — it loads every sub-flow and expands every `ref` with no browser, so typos never cost a page load. It cannot catch a malformed `when:` predicate; those fail mid-run.
2. `run` once; on failure read `step` from the JSON error, plus the `screenshot` / `dom` paths `run` wrote and reported there.
3. Re-probe just that region: `llm-browser dom --selector "form#search" --level medium --max-depth 3`.
4. Fix **one** selector or one wait, then `run --from <failed step>` — never restart from the top while the browser is already on the right screen.
5. Keep an attempts table in the PR or notes: step · selector tried · what the page actually showed · outcome.
6. Stop and ask after 3 failed attempts on the same step, on any `human_needed: true`, on a captcha, or when the fix would need a never-click control.

## Deliverables

- One flow file per screen (or per atomic intent) under `flows/<domain>/`, plus the `recovery_*` flows, each opening with the domain-rules comment block.
- `flows/<domain>/selector_map.yaml`, grouped by page area — flows in a directory always pair with the map in that same directory.
- A `just` target that encodes the pairing, so no caller types it by hand:

```just
_run FLOW DATA="{}":
    @llm-browser run --flow "{{ FLOW }}" --selector-map "$(dirname {{ FLOW }})/selector_map.yaml" --data '{{ DATA }}'
```

- A smoke-run log: the JSON from one successful `run`, secrets redacted.
- The never-click comment in every flow that sits next to a destructive control.
- The attempts table for anything that took more than one try.

## Checklist

1. Intake answered, or the assumed defaults stated back to the user.
2. Domain rules and the never-click list are a comment block at the top of every flow.
3. Exactly one page load across the whole flow set.
4. No `eval:` step anywhere; anything that would need one is filed as a library gap.
5. Every selector works on the driver in use — no XPath if that driver is `nodriver`; no `nth-child`, no hashed classes, no `#`-prefixed numeric ids.
6. Every navigation and XHR click is followed by a `wait_for`; no `wait_after` sleeps left.
7. Every `when:` predicate matches FLOWS → Conditions, `eq` included.
8. `optional: true` only where the page state genuinely varies.
9. Every secret is a param, redacted, and never echoed.
10. `llm-browser validate` exits 0 for every flow with its selector map.
11. One clean end-to-end `run`, log captured.
12. The `just` target is committed and run once from a clean checkout.
