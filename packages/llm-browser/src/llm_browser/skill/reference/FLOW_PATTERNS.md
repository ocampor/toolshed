# Flow Patterns

Field-tested, JavaScript-free YAML for the situations that cost the most time. Language
reference: [FLOWS.md](FLOWS.md); driver limits: [DRIVERS.md](DRIVERS.md). `eval:` is not a
pattern here — if a page needs one, the missing primitive belongs in the library.

**XPath is not portable.** Every `{ xpath: ... }` and `:has-text(...)` below needs `patchright`
or `camoufox`; on `nodriver` only real CSS reaches the page ([DRIVERS.md → Selector and key
support](DRIVERS.md#selector-and-key-support)). Each pattern names its CSS equivalent.

| Instead of `eval` for | Use |
|---|---|
| Picking an autocomplete item | [Autocomplete](#autocomplete-jquery-ui-and-friends) |
| Clearing a framework-bound input | [Framework-bound text input](#framework-bound-text-input-angular-vue-react) |
| Reading an input's current value | [Reading a live input value](#reading-a-live-input-value) |
| Toggling a hidden or styled checkbox | [Custom checkbox](#custom-checkbox-hidden-input-styled-label) |
| Polling until a loader disappears | `wait_for` with `state: hidden` or `detached` |
| Enumerating `<select>` options | `dom` with the select's selector |
| Reading a generated id | [Rotating-prefix ids](#rotating-prefix-ids) |

## Reading the page

`dom` sanitizes; `find` does not. `find --selector … --all` returns each match's raw `outerHTML`,
so `data-*` and `aria-*` are readable per candidate without a page-sized dump.

Attributes surviving each `--level`, as rendered by `sanitize_html_fragment`:

| `--level` | Attributes kept | Also |
|---|---|---|
| `low` | every attribute except `style` | the default |
| `medium` | lxml's `safe_attrs` (`id`, `class`, `name`, `type`, `value`, `alt`, `title`, `for`, table attrs, …) plus `href`, `src`; no `style` | drops `data-*`, `aria-*`, `role`, `placeholder` |
| `high` | `medium` minus `href` and `src` | for full-page captures where links are noise |
| `xhigh` | `id`, `name`, `role`, `type`, `value`, `placeholder`, `alt`, `title` only | unwraps `div`/`span`/`section`, so structure reads at a glance |

- Scripts, inline styles, `style` attributes, comments, `<meta>` and `<link>` are stripped at
  **every** level — the levels differ only in attributes, killed tags and data-URI truncation.
- `role` and `placeholder` survive at `xhigh` but **not** at `medium`; `data-*` and `aria-*`
  survive only at `low`. Pick the level from this table, not by stepping down through them.
- The `dom` *step* has no `level:` field: in a flow it is always `low`.

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
See [DRIVERS.md](DRIVERS.md) for the escape-hatch list.

```yaml
- { name: continue, selector: "#btnContinuar", action: click, dispatch: true }
- { name: next screen, selector: "#confirmacion", action: wait_for, state: attached, timeout: 15000 }
```

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
