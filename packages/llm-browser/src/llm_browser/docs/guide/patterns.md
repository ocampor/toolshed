# Flow Patterns

Field-tested, JavaScript-free YAML for the situations that cost the most time. Language
reference: `reference/steps`; driver limits: the `llm_browser.drivers` module docs. `eval:` is not a
pattern here — if a page needs one, the missing primitive belongs in the library.

**XPath is not portable.** Every `{ xpath: ... }` and `:has-text(...)` below needs `patchright`
or `camoufox`; on `nodriver` only real CSS reaches the page (see `llm_browser.drivers`). Each pattern names its CSS equivalent.

| Instead of `eval` for | Use |
|---|---|
| Picking an autocomplete item | [Autocomplete](#autocomplete-jquery-ui-and-friends) |
| Clearing a framework-bound input | [Framework-bound text input](#framework-bound-text-input-angular-vue-react) |
| Reading an input's current value | [Reading a live input value](#reading-a-live-input-value) |
| Toggling a hidden or styled checkbox | [Custom checkbox](#custom-checkbox-hidden-input-styled-label) |
| Polling until a loader disappears | `wait_for` with `state: hidden` or `detached` |
| Enumerating `<select>` options | `dom` with the select's selector |
| Reading a generated id | [Rotating-prefix ids](#rotating-prefix-ids) |
| Paging a result list | [Pagination](#pagination) |
| Clicking a card that has no id | [List → detail](#list--detail) |
| Polling until a framework has painted | [SPA hydration](#spa-hydration) |

## Before writing a step

Two calls per page, whatever the flow: **survey, then explore the targets it
named.** The first says what the page is made of; the second checks every
selector you are about to write, together.

```bash
llm-browser survey                      # landmarks, link shapes, repeats, hydration
llm-browser explore --targets flow.yaml # every selector of the flow, one page call
```

```yaml
# flow.yaml — one entry per step you are about to write
- { selector: "tr.athing", extract: { title: ".titleline > a" } }   # from repeats
- { selector: ".morelink", intent: click }                          # from landmarks
```

`survey` reads only: it never clicks and never scrolls. `repeats` is where a
list's selector and its real length come from, `link_shapes` where a
`a[href^=…]` for a whole section does, and `hydration.since_navigation_ms` is
the number to size the flow's first `wait_for` from. `explore --targets` then
answers each one against its own `--intent`, exiting non-zero unless every
verdict is `ok` — the flow failing at authoring time instead of on the run.
Targets are CSS and at most twenty per call; one the page cannot parse answers
`error: not css` and the rest still answer.
See `reference/session` under `survey` for every field.

`llm-browser explore --selector … --intent <what the step will do>` is the same
answer for one selector, when a step is all that is in question.

A page that reveals a control on a click is **two** rounds, not one: survey,
write the click, run it, then survey again. Wikipedia's header search is the
example — `#searchInput` is on the page and hidden, and the toggle click
replaces the whole form with one that has no id at all. `explore` says
`not_actionable` / `why_not: ["hidden"]` on the first round, which is the
signal to go round again; `validate` never will, because it checks the flow's
schema and never opens the page.

| `--intent` | `ok` when | Read these |
|---|---|---|
| `read` | `count >= 1` | `count`, `sample`, `empty_fields` |
| `wait` | `count == 1` | `count`, `since_navigation_ms` |
| `click` | `count == 1` and `first.clickable` | `first.why_not`, `first.covered_by`, `first.nested_controls`, `candidates` |
| `fill` | `count == 1`, visible and enabled | `first.visible`, `first.enabled`, `first.tag` |

- `wait_for` timeout: **3x `since_navigation_ms`, minimum 3000** — measured off
  the page's own clock, so a call made long after the load still sizes the wait
  for a cold one. `since_call_ms` is the same wait seen from the caller.
- `first.why_not` names what a click would hit instead: `covered` (with
  `covered_by`), `offscreen`, `moving`, `hidden`, `disabled`,
  `no-pointer-events`, `not-interactive`. Only `offscreen` is not an obstacle —
  the drivers scroll first, and so does `explore` before it hit-tests. `nested_controls` is the other half: a card-sized
  anchor wrapping its own dismiss button takes the click you meant for the card.
- `candidates` are selectors checked to match that same element and nothing
  else; `stability` says how much of the one you wrote a redeploy is likely to
  take with it (`data-testid` > `aria` > `id` > `class-hash` > `positional`).

## Reading the page

`dom` sanitizes; `find` does not. `find --selector … --all` returns each match's raw `outerHTML`,
so `data-*` and `aria-*` are readable per candidate without a page-sized dump.

Attributes surviving each `--level`, as rendered by `sanitize_html_fragment`:

| `--level` | Attributes kept | Also |
|---|---|---|
| `low` | every attribute except `style` | the default |
| `medium` | lxml's `safe_attrs` (`id`, `class`, `name`, `type`, `value`, `alt`, `title`, `for`, table attrs, …) plus `href`, `src`; no `style` | drops `data-*`, `aria-*`, `role`, `placeholder` |
| `high` | `medium` minus `href` and `src` | for page-sized `dom` reads where links are noise |
| `xhigh` | `id`, `name`, `role`, `type`, `value`, `placeholder`, `alt`, `title` only | unwraps `div`/`span`/`section`, so structure reads at a glance |

- Scripts, inline styles, `style` attributes, comments, `<meta>` and `<link>` are stripped at
  **every** level — the levels differ only in attributes, killed tags and data-URI truncation.
- `role` and `placeholder` survive at `xhigh` but **not** at `medium`; `data-*` and `aria-*`
  survive only at `low`. Pick the level from this table, not by stepping down through them.
- The `dom` step's `level:` defaults to `low`; the CLI's `--level` and
  `session.dom(level=)` take the same four values.
- On an SPA that hydrates late, [explore the selector](#before-writing-a-step)
  before writing the `read`. The run never raises that mistake — a child
  selector matching nothing reads as `None` and the step still passes.

## Autocomplete (jQuery UI and friends)

Clear, type slowly enough to trigger the async search, wait for the menu, then take the item.

```yaml
- { name: clear currency, selector: { id: "moneda" }, action: fill, value: "" }
- { name: type currency, selector: { id: "moneda" }, action: type, value: "{{ currency }}", delay: 30 }
- { name: menu appears, selector: "li.ui-menu-item", action: wait_for, state: attached, timeout: 6000 }
- { name: pick currency, selector: "li.ui-menu-item", action: pick, value: "{{ currency }}" }
```

- `wait_for` replaces the `wait_after: 1500` sleep: it returns as soon as the menu exists, and
  fails loudly when the search returned nothing.
- `pick` is the portable choice — plain CSS, every driver — but it compares `text_content` with
  `==`. When the item's text carries surrounding whitespace or extra words, `pick` raises
  `No element with text …` and you need a text-matching selector instead:
  `selector: { xpath: "//li[contains(@class,'ui-menu-item') and contains(.,'{{ currency }}')]" }`
  with `action: click` (patchright / camoufox only).

## Framework-bound text input (Angular, Vue, React)

`fill` dispatches one `input` event, which some two-way bindings ignore. Focus, select all, type
over the selection.

```yaml
- { name: focus amount, selector: { id: "importe" }, action: click }
- { name: select all, selector: { id: "importe" }, action: press, key: "Control+a" }
- { name: type amount, selector: { id: "importe" }, action: type, value: "{{ amount }}", delay: 30 }
```

- **`nodriver` cannot do this.** Its `press` special-cases named keys only; `Control+a` falls
  through to `send_keys`, which **types the literal text `Control+a` into the field and reports
  success**, so the next `type` appends to it and the flow ships a wrong value with a green run.
  Use `patchright` or `camoufox` for this pattern.

### `type` vs `fill`

| | `fill` | `type` |
|---|---|---|
| What it does | clears, then sets the value in one shot | sends the value key by key |
| Events | one `input` | full `keydown` / `keypress` / `input` / `keyup` per character |
| Use for | plain HTML inputs; clearing a field with `value: ""` | custom widgets, autocompletes, JS validation, framework-bound inputs |
| Cost | fast | `delay: 30`-`50` per key |

- Click the field first when the widget only initialises on focus.

## Reading a live input value

`dom` and `find` return markup, so a framework-bound `<input>` looks empty. `read` with
`attribute: value` reads the DOM property instead.

```yaml
- name: read client fields
  selector: "#cp"
  action: read
  extract:
    cp: { attribute: value }
```

## Custom checkbox (hidden input, styled label)

A visually hidden `<input>` fails `check`'s actionability wait. Click the visible `<label>`, gated
on the widget's state class so the step stays idempotent.

```yaml
- name: enable simplified isr
  selector: "label[for='0168']"
  action: click
  when:
    - { element_exists: { selector: "label[for='0168'] span.checkOff" } }
```

- With no state class, gate on `element_missing` for whatever the toggle reveals. A standard
  checkbox just takes `action: check` with `checked: true`.

## Dismissing a modal

Click only when the modal is actually up; `optional: true` covers the race where it self-closed.

```yaml
- name: dismiss modal
  selector: "div.modal[style*='block'] button[data-dismiss='modal']"
  action: click
  optional: true
  when:
    - { element_exists: { selector: "div.modal[style*='block']" } }

- { name: modal gone, selector: ".modal-backdrop", action: wait_for, state: detached, timeout: 5000 }
```

- When only the button's *text* distinguishes it, the CSS above cannot select it; use
  `{ xpath: "//div[contains(@class,'modal') and contains(@style,'block')]//button[contains(text(),'Aceptar')]" }`
  and accept the patchright / camoufox requirement.
- Keep it in its own `recovery_dismiss_modal.yaml` and reference it from the happy path as an
  `optional: true` `run-flow` step, so one file serves the flow and a manual rescue.

## Rotating-prefix ids

Sites that regenerate ids per deployment (`135textbox78` → `457textbox78`) keep the *suffix*
stable. Probe the live id off one known element, then rewrite the map in one pass.

```yaml
# detect_prefix.yaml — no JS, no guessing
steps:
  - name: detect prefix
    selector: "input[id$='textboxautocomplete32']"
    action: read
    extract:
      probe_id: { attribute: id }
```

```bash
llm-browser run --flow flows/detect_prefix.yaml
# then rewrite the old prefix to the new one across selector_map.yaml, once, and re-run
```

- Numeric-leading ids are not valid CSS ids: write `{ id: "135textbox78" }` (resolves to
  `[id="135textbox78"]`), never `#135textbox78`.
- A label-anchored selector needs no healing at all. In CSS, go through the label's `for`
  (`select[id="457select7"]` — the `for` value *is* the id) or `:has()`:
  `div:has(> label[for='0168']) select`. Where neither works, the XPath form is
  `{ xpath: "//label[contains(text(),'Copropiedad')]/following::select[1]" }` — patchright /
  camoufox only.

## Disambiguating same-text controls

Pages often carry several copies of a button, one visible.

```bash
llm-browser find --selector "button" --all
```

- `--all` prints each match's `outerHTML`, so pick the copy with a unique id or attribute
  (`@entidad`, a semantic class) and select on that — portable to every driver.
- `find --selector "//button[contains(text(),'Aceptar')]" --all` narrows the listing first, but
  needs patchright or camoufox.
- Confirm the copy you chose is the live one with `wait_for` `state: visible` before clicking.

## Submit handlers that ignore real clicks

`dispatch: true` fires an untrusted DOM `click` — last resort, only for a JS-bound submit or
confirm button. It emits `isTrusted=false` on **every** driver, camoufox included: camoufox's
stealth is fingerprint-level and does not rewrite `Event.isTrusted` for a page-created event.
See `llm_browser.drivers` for the escape-hatch list.

```yaml
- { name: continue, selector: "#btnContinuar", action: click, dispatch: true }
- { name: next screen, selector: "#confirmacion", action: wait_for, state: attached, timeout: 15000 }
```

## Pagination

A paged list moves forward by clicking its own control; nothing on the page takes a page
number. Click `Next`, let the framework swap the rows in, then re-read the same container.

```yaml
steps:
  - name: next page
    selector: "button[aria-label='Next']"
    action: click
    when:
      - { element_exists: { selector: "button[aria-label='Next']" } }

  - { name: settle, action: think, min_ms: 2000, max_ms: 6000 }

  - name: rows redraw
    selector: "[componentkey='SearchResultsMainContent']"
    action: wait_for
    state: stable
    settle: 1000
    timeout: 20000

  - name: read page
    selector: "[componentkey='SearchResultsMainContent'] p"
    action: read
    extract:
      line: { attribute: textContent }
```

- `fill` and `pick` are the wrong tools here: `fill` sets an input's value and a pager is a
  `<button>`, while `pick` clicks the list item whose text matches — an item, never a control.
- `Next` disappears on the last page; the `when:` guard turns that into a no-op instead of a
  timeout, and `optional: true` on the step is the after-the-fact equivalent.
- Where the rows are a flat `<p>` sequence with no per-row wrapper, read the `<p>`s and split
  them locally on the "Posted … ago" node rather than inventing a row selector the page lacks.
- Plain CSS throughout, so this one runs on every driver.

## List → detail

Cards on a framework-rendered list often carry no id and machine-generated classes. Anchor on
the attributes the framework and its authors keep stable instead.

| Hook | Example | Why it holds |
|---|---|---|
| `data-testing-id` | `[data-testing-id='mission-application-title']` | authored for tests; the most stable hook a page can offer |
| `componentkey` | `[componentkey='SearchResultsMainContent']` | stable string keys; UUID-bearing ones rotate per load — match with `^=` |
| `aria-label` | `button[aria-label='Next']` | tracks the copy, not the build |
| row text | `(//main//p[contains(normalize-space(.), '{{ title }}')])[1]` | last resort when the card has no attribute at all (XPath: patchright / camoufox) |

```yaml
params: [title]
steps:
  - name: open card
    selector: { xpath: "(//main//p[contains(normalize-space(.), '{{ title }}')])[1]" }
    action: click

  - { name: read a bit, action: think, min_ms: 2000, max_ms: 5000 }

  - name: detail pane
    selector: "[componentkey^='JobMatchRef_']"
    action: wait_for
    state: visible
    timeout: 20000

  - name: read detail
    selector: "[componentkey^='JobMatchRef_']"
    action: read
    extract:
      link: { child_selector: "a[href*='/jobs/view/']", attribute: href }
      body: { attribute: textContent }
```

- The record's id exists only after the click — it surfaces as the suffix of
  `[componentkey^='JobMatchRef_']` and inside the detail link's `href`. Read it back, never
  build it.
- No CSS equivalent of the click: `pick` needs a selector matching each card's own container,
  and this list has none — it's a flat `<p>` run (see Pagination above). Aiming `pick` at
  `main p` matches hundreds of unrelated nodes, so the XPath click is the only option here.
- There is no `back` action. Click the site's own back control, or page back within the same
  tab — re-entering the list via a `run-flow` step re-runs that flow's own `goto`, so it costs
  the same navigation, not less.

## SPA hydration

`goto` returns on `domcontentloaded` and the framework paints afterwards. A fixed `think`
guesses at that delay; `wait_for` on a selector only the hydrated page has returns the moment
it appears, and bounds the wait at a real timeout rather than a guess.

```yaml
steps:
  - name: results hydrate
    selector: "[componentkey='SearchResultsMainContent']"
    action: wait_for
    state: visible
    optional: true
    timeout: 20000

  - { name: last paint, action: think, min_ms: 800, max_ms: 2000 }

  - name: read results
    selector: "[componentkey='SearchResultsMainContent'] p"
    action: read
    extract:
      line: { attribute: textContent }
```

- `optional: true` keeps a server-rendered variant of the page from failing on a landmark it
  never mounts; the short `think` afterwards covers the final paint, which no selector
  announces.
- A half-hydrated page answers a read with nav chrome, a skeleton or `Loading…`, and the step
  still succeeds. Nothing in the flow catches that, so check the selector before writing the
  step: `llm-browser explore --selector "[componentkey='SearchResultsMainContent'] p"` reports
  how many rows it matches right now and how much text they carry, and a stub shows up as a
  count far below the real list (see
  `reference/session` under `explore`).
- When the stub has the right shape but placeholder text, `wait_for` `state: stable` with
  `settle: 1000` on the container waits for the text to stop changing instead.
- When hydration is what unlocks a field — an input a checkbox enables — `wait_for`
  `state: enabled` on that field is the precise wait (the states are in
  `reference/waits`).

## One-shot pages

A 1Password one-time share link opens exactly once — the second view is "Maximum views
reached". Rehearsing a flow against one burns the only view it has.

```yaml
steps:
  - name: reveal password
    selector: "li[aria-label='Reveal password']"
    action: click

  - { name: close the menu, action: press, key: "Escape" }

  - { name: rendered, action: think, min_ms: 500, max_ms: 1500 }

  - name: credentials
    selector: "body"
    action: read
```

No `extract:` needed — a bare `read` gives the default `text` field (see
`reference/steps` under `ReadStep`).

- No `goto` in the flow. Open the link by hand in a live tab and address that tab:
  `llm-browser --cdp-url … --target-id … run --flow one_shot.yaml` (see `llm-browser --help`). A
  flow that navigates itself spends the view on the rehearsal.
- Check the shape with `llm-browser validate --flow one_shot.yaml` and rehearse the steps on a
  page you can reload; the share link gets the one real run.
- `press` without a `selector` goes to the focused element — the way out of a menu that stays
  open over the next field. One `Escape` per menu.
- Reveal *every* concealed field in that run: one `li[aria-label='Reveal password']` click per
  field, all before the read.
- `read` on `body` is the safe default when the layout is unknown (`dom` on `body` also works
  since 0.13.0), but both hand back the whole page. Once you know where the fields sit, read
  the smallest container holding them.

## Migrating older flows

What `llm-browser validate` does with each retired spelling — the middle column is the dangerous
one, because a clean exit 0 is not a clean flow.

| Old | What happens today | Replacement |
|---|---|---|
| `action: wait` (`quiet_ms`, `timeout_s`) | rejected at load | `action: wait_for`, `state: stable`, `settle:` and `timeout:` in ms |
| `action: read_values` | rejected at load | `read` with `extract: { name: { attribute: value } }` |
| `action: dismiss_modal` | rejected at load | `click` with `when: [{ element_exists: … }]` and `optional: true` |
| `action: click_visible` | rejected at load | `wait_for` `state: visible`, then `click` |
| `action: click_all` | rejected at load | one `click` per target, or a `run-flow` child per item |
| `action: modify_dom` | rejected at load | the matching action; if none exists, request it upstream |
| `action: wait_for_load_state` | rejected at load | `goto`'s `wait_until:` |
| `wait_after: <ms>` | **accepted and executed** — `steps.py` sleeps for it | a `wait_for` step naming what the click produced |
| `fields:` block | **accepted and ignored** — a real `BaseStep` field that nothing reads | one step per field |
| `checkpoint: true` | **accepted and ignored** — not a field at all; pydantic drops it | end the flow before the human's step and re-invoke afterwards |
| `eval:` | accepted and executed | the patterns above; a page that still needs JS is a library gap |
