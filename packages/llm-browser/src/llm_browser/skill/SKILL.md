---
name: llm-browser-flows
description: Author, debug and hand over llm-browser YAML flows for a specific site — use when asked to automate a web app, scrape a logged-in page, or fix a flow whose selector broke.
---

# Authoring llm-browser flows

- Language reference: `FLOWS.md` in the llm-browser package (actions, `when` conditions, selector forms, extract specs).
- Copy-paste YAML for hard widgets: `docs/FLOW_PATTERNS.md` there too (autocomplete, framework-bound inputs, hidden checkboxes, modal dismiss, rotating ids).
- This file is the method: what to ask, how to explore, which selector to pick, where to wait, when to stop.

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
| Driver in use (`patchright`, `camoufox`, `nodriver`) | headless viability, key chords, pacing | `patchright`, headed, attach mode |
| Existing flows directory and `selector_map.yaml` | new work extends them | `flows/<domain>/` and `flows/<domain>/selector_map.yaml` |

- State the defaults you assumed back to the user in one line before you start.
- Domain rules stay the consumer's: copy them verbatim into a comment block at the top of every flow file you write, never into the library.

## Reconnaissance, fastest path

- `attach` when the user already runs a Chromium with a warmed, logged-in profile; `daemon` when nothing is running and llm-browser should own the browser. `open` is single-shot — the browser dies with the CLI process.
- Wrap `daemon` in the project's own target (a `just` recipe) so it always gets the warmed `--profile`; a bare `daemon` starts a cold identity and re-triggers the login wall.
- Navigate **once**. After the first `goto`, move by clicking. A second `goto` throws away SPA state and, on a site with fraud detection, can lock the account.
- Map region by region. A full-page dump wastes the budget and hides the form you need.

```bash
chromium --remote-debugging-port=9222 --user-data-dir="$HOME/.cache/llm-browser/attach-profile"
llm-browser attach --cdp-url http://localhost:9222
llm-browser --cdp-url http://localhost:9222 --target-id <target_id> goto --url https://portal.example.com/invoices
llm-browser --cdp-url http://localhost:9222 --target-id <target_id> dom --selector "main" --level xhigh --max-depth 3
llm-browser --cdp-url http://localhost:9222 --target-id <target_id> dom --selector "form#search" --level medium --max-depth 3
llm-browser --cdp-url http://localhost:9222 --target-id <target_id> find --selector "input[name='rfc']" --all
llm-browser --cdp-url http://localhost:9222 --target-id <target_id> screenshot
```

- Without attach: `llm-browser daemon --url https://portal.example.com --profile ./.browser-profile --executable /usr/bin/chromium`, then the same `dom` / `find` commands with no `--cdp-url` / `--target-id` prefix, and `llm-browser stop` at the end.

| `--level` | Keeps | Use it for |
|---|---|---|
| `xhigh` | `id`, `name`, `role`, `type`, `value`, `placeholder`, `alt`, `title`; unwraps `div`/`span`/`section` | structure — which forms, tables and controls exist |
| `medium` | the above plus `class`, `href`, `src`, table attributes; drops `style` | picking id / name / class / href selectors |
| `low` | everything, uncleaned | debugging — and the only level where `data-*` and `aria-*` survive |
| `high` | `medium` minus `src` and `href` | full-page captures where links are noise |

- Probe candidates in batches: one `find --selector ... --all` per candidate, reading `count`. `count: 1` is a selector, `count: 0` is wrong, `count: > 1` needs narrowing.
- Same-text controls are the usual trap — three "Aceptar" buttons, one visible. `find --all`, then pick the copy with a unique id or attribute, and prove it is the live one with a `wait_for` `state: visible` before clicking.
- Try the user's known ids first. Stop the moment one stable selector exists per target; do not enumerate the page.

## Selector rules (ranked)

| Rank | Form | Example | Notes |
|---|---|---|---|
| 1 | stable `id` | `selector: { id: "rfc" }` | resolves to `[id="rfc"]` |
| 2 | `name` | `selector: "input[name='rfc']"` | survives markup redesigns |
| 3 | `data-*` / `aria-label` / role+text | `selector: "[data-testid='submit-row']"` | visible only under `--level low` |
| 4 | label-anchored XPath | `selector: { xpath: "//label[contains(text(),'Copropiedad')]/following::select[1]" }` | the answer for rotating ids: labels do not rotate |
| 5 | stable class or structural CSS | `selector: { css: "form#search input[type='date']" }` | hand-written class only; anchor on an id, then descend |
| 6 | XPath by button text | `selector: { xpath: "//button[normalize-space()='Buscar']" }` | brittle against copy changes |

- Never `nth-child` on a list: row order changes between loads and you silently read the wrong row.
- Never a generated or hashed class (`.css-1x2y3z`, `.jsx-8842`) — it changes every deploy.
- Never `#135textbox78`: an id starting with a digit is invalid CSS. Write `{ id: "135textbox78" }`.
- One fallback per map entry (`primary` / `fallback`); a deeper chain hides which branch matched.
- Group refs by page area (`login.*`, `search.*`, `results.*`) so the map reads like the screen.
- Keep templated selectors (`{{ }}` inside an xpath) inline in the flow; map entries name constants.

**Detect rotating ids**: load the page twice in a fresh tab, `dom --selector "form" --level xhigh` both times, diff. Ids differing only in a leading numeric or hash prefix rotate.

| Situation | Do this |
|---|---|
| A stable label sits next to the control | rank 4 label-anchored XPath — no healing needed, prefer it |
| No label, or many identical labels | keep the id and heal the prefix |
| Prefix healing | probe the live id with `read` + `attribute: id` off an `[id$='<stable suffix>']` selector, then rewrite old prefix → new prefix across `selector_map.yaml` in one deterministic pass |

- Healing is a consumer-side script, not a library feature, and it is one-shot and auditable — never re-infer selectors per call.
- Full worked example: FLOW_PATTERNS → "Rotating-prefix ids".

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
- `stable` needs `settle` strictly less than `timeout` — the flow refuses to load otherwise.
- `timeout` = 3× the latency you actually observed, minimum `3000` (also the default).
- `optional: true` for anything dismissable, so a missing banner is a skip and not a failure. It is for variant page state, never for "this might flake".
- Branch on presence with `when` rather than a wait you expect to fail.

```yaml
- { name: results appear, selector: "#results tbody tr", action: wait_for, state: attached, timeout: 15000 }
- { name: spinner clears, selector: ".spinner", action: wait_for, state: hidden, timeout: 9000 }
- { name: total settles, selector: "#total", action: wait_for, state: stable, settle: 800, timeout: 12000 }
- { name: dismiss banner, selector: ".cookie-banner .close", action: click, optional: true, timeout: 3000 }
- name: close popup
  selector: ".popup .close-btn"
  action: click
  when:
    - { element_exists: { selector: ".popup" } }
```

## `type` vs `fill`

| | `fill` | `type` |
|---|---|---|
| What it does | clears, then sets the value in one shot | sends the value key by key |
| Events | one `input` | full `keydown` / `keypress` / `input` / `keyup` per character |
| Use for | plain HTML inputs; clearing a field with `value: ""` | custom widgets, autocompletes, JS validation, framework-bound inputs |
| Cost | fast | `delay: 30`-`50` per key |

- Click the field first when the widget only initialises on focus.
- `fill` alone often will not clear a framework-bound input: `click` to focus, `press` with `key: "Control+a"`, then `type` over the selection.
- Key chords need `patchright` or `camoufox`; `nodriver`'s `press` handles named keys and single characters only.

## Flow structure

- One flow per screen — or per atomic intent when a human has to act mid-screen. Splitting `fill` / `submit` / `confirm` into separate files is what lets the handoff land between them.
- One flow per optional field, so a caller can run only the fields a probe step said were missing.
- Compose with `run-flow`; children are **leaf-only** (a child may not contain `run-flow`). A `flow:` reference resolves relative to the parent flow's own directory; a `schema_path:` is CWD-relative or absolute.
- Declare every input in `params:`; use `{{ name }}` in any string value. Optional params: `{ region: { required: false, default: MX } }`.
- Branch in the parent, not the child: `when:` on the `run-flow` step keeps typed booleans and nulls intact, which templating a child's `data:` block cannot.
- `when:` predicates: `{ field: X, op: is_truthy | eq | not_null }`, `{ element_exists: { selector: S } }`, `{ element_missing: { selector: S } }`. All entries are AND'ed. `element_missing` is the idempotent-toggle guard: only click when the post-click element is not already there.
- `recovery_*` flows: one per known dead end, named for what it undoes (`recovery_dismiss_modal.yaml`, `recovery_session_timeout.yaml`). Keep them idempotent, run them before retrying the failed step, and reference the same file from the happy path as an `optional: true` `run-flow` step.
- Outputs: `read` + `extract` for rows and fields, `parse` + `schema_path` for typed rows, `dom` for a snapshot, `download` for files. Add `path:` to also land the result on disk. `extract` with `attribute: value` reads a live input's value — markup from `dom` or `find` will not show it.
- Secrets are params, never literals: `value: "{{ password }}"`, supplied via `--data`, fetched and used in one shell command so the value never reaches tool output. From Python, `run_flow(..., redact=[password])` replaces it with `***` in outputs, logs, errors and retry hints.
- Failure capture is automatic: `BrowserSession(capture="screenshot" | "dom" | "both")`. `FlowError` carries `step`, `screenshot`, `dom`, the `outputs` collected so far, and a `retry_hint` naming the failed step.
- `FlowError.human_needed` true means a password prompt, a live captcha or an interstitial — retrying is useless. Tell the user which screen it is, that they must log in or clear the challenge in the attached browser, and the exact `run --from <step>` to resume with.
- There is no in-flow pause. A flow that needs a human ends before the human's step; the caller prints the instruction and is re-invoked afterwards against the same daemon.

## Anti-detection

- Pacing is the driver's job: `--behavior-config <file>` jitters keystrokes, clicks and pauses on every input. A fixed cadence is itself a fingerprint; do not hand-roll sleeps in its place.
- `dispatch: true` is a last resort for a JS-bound submit or confirm handler that ignores a real click. It fires an untrusted event (`isTrusted=false`); `camoufox` masks that, the Chromium drivers do not. Never on an ordinary control.
- One `goto` per session; no deep links into inner pages. If a page cannot be reached by clicking, stop and ask the user to open it, then run the flow against the page they opened.
- Sensitive sites (banking, tax, anything with fraud lockout): headed, attached to a warmed real profile, `camoufox` if it must be headless, no parallel sessions against one account, and no retry loop on a login step — a second failure means stop and ask.
- Never-click enforcement: do not write the step. Leave a comment naming the forbidden control so the omission reads as deliberate.

```yaml
# never-click: #btnSellar ("Sellar") — timbrado is irreversible; the human presses it.
```

## No JavaScript in flows

- Do not write `eval:` steps. If a page seems to need one, the missing primitive belongs upstream in llm-browser — file it, do not patch around it.

| Instead of `eval` for | Use |
|---|---|
| Clearing a framework-bound input | `click`, then `press` `key: "Control+a"`, then `type` |
| Toggling a hidden / styled checkbox | `click` the visible `<label>`, gated by `when: element_exists` on the widget's state class |
| Picking an autocomplete item | `type` with `delay`, `wait_for` the menu `attached`, `click` the item by text XPath |
| Reading an input's current value | `read` with `extract: { field: { attribute: value } }` |
| Reading a generated id (prefix probe) | `read` with `extract: { probe: { attribute: id } }` on `[id$='<stable suffix>']` |
| Polling until a loader disappears | `wait_for` `state: hidden` or `detached` |
| Enumerating `<select>` options | `dom` with the select's selector |

## Migrating older flows

| Removed | Replacement |
|---|---|
| `action: wait` (`quiet_ms`, `timeout_s`) | `action: wait_for`, `state: stable`, `settle:` (ms), `timeout:` (ms) |
| `wait_after: <ms>` after a click or navigation | a `wait_for` step naming what the click produced |
| `fields:` block (autocomplete / checkbox / text / select) | one step per field |
| `read_values` | `read` with `extract: { name: { attribute: value } }` |
| `dismiss_modal` | `click` with `when: [{ element_exists: ... }]` and `optional: true` |
| `click_visible` | `wait_for` `state: visible`, then `click` |
| `click_all` | one `click` per target, or a `run-flow` child per item |
| `modify_dom` | the matching action; if none exists, request it upstream |
| `wait_for_load_state` | `goto`'s `wait_until:` |
| `checkpoint: true` | end the flow before the human's step (see Library gaps) |

## Library gaps

Report these to the user rather than working around them; the fix belongs in llm-browser.

| Gap | Consequence |
|---|---|
| No in-flow human pause (`checkpoint:` is not a field and is silently ignored) | split the flow and re-invoke after the human acts |
| `press` on `nodriver` supports named keys and single characters only — no chords | the `Control+a` clear needs `patchright` or `camoufox` |
| `check` cannot target a visually hidden input | needs a clickable label or a state class to gate on |
| No `resume` command | `run --from <step>` against the still-open daemon is the only re-entry |

## Iterate loop

```bash
llm-browser validate --flow flows/search.yaml --selector-map flows/selector_map.yaml
llm-browser run --flow flows/search.yaml --selector-map flows/selector_map.yaml --data '{"rfc":"XAXX010101000"}'
llm-browser run --flow flows/search.yaml --selector-map flows/selector_map.yaml --data '{"rfc":"XAXX010101000"}' --from "results appear"
```

1. `validate` first — it loads every sub-flow and expands every `ref` with no browser, so typos never cost a page load.
2. `run` once; on failure read `step`, `screenshot` and `dom` from the JSON error.
3. Re-probe just that region: `llm-browser dom --selector "form#search" --level medium --max-depth 3`.
4. Fix **one** selector or one wait, then `run --from <failed step>` — never restart from the top while the browser is already on the right screen.
5. Keep an attempts table in the PR or notes: step · selector tried · what the page actually showed · outcome.
6. Stop and ask after 3 failed attempts on the same step, on any `human_needed: true`, on a captcha, or when the fix would need a never-click control.

## Deliverables

- One flow file per screen (or per atomic intent) under `flows/<domain>/`, plus the `recovery_*` flows, each opening with the domain-rules comment block.
- `flows/<domain>/selector_map.yaml`, grouped by page area — flows in a directory always pair with the map in that same directory.
- A `just` or `make` target that encodes the pairing, so no caller types it by hand:

```make
_run FLOW DATA="{}":
    @llm-browser run --flow "{{ FLOW }}" --selector-map "$(dirname {{ FLOW }})/selector_map.yaml" --data '{{ DATA }}'
```

- A smoke-run log: the JSON from one successful `run`, secrets redacted.
- The never-click comment in every flow that sits next to a destructive control.
- The attempts table for anything that took more than one try.

## Checklist

1. Intake answered, or the assumed defaults stated back to the user.
2. Domain rules and the never-click list are a comment block at the top of every flow.
3. Exactly one `goto` across the whole flow set.
4. No `eval:` step anywhere; anything that would need one is filed as a library gap.
5. Every selector is rank 1-4, or rank 5-6 with a written reason; no `nth-child`, no hashed classes, no `#`-prefixed numeric ids.
6. Every navigation and XHR click is followed by a `wait_for`; no `wait_after` sleeps left.
7. Every `stable` wait has `settle` < `timeout`; every timeout ≥ 3000.
8. `optional: true` only where the page state genuinely varies.
9. Every secret is a param, redacted, and never echoed.
10. `llm-browser validate` exits 0 for every flow with its selector map.
11. One clean end-to-end `run`, log captured.
12. The `just`/`make` target is committed and run once from a clean checkout.
