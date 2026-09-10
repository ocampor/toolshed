# Flow Patterns

Field-tested, JavaScript-free YAML for the situations that cost the most time. Language
reference: [FLOWS.md](../FLOWS.md); authoring method: `llm-browser skill show`. `eval:` is not a
pattern here — if a page needs one, the missing primitive belongs in the library.

## Autocomplete (jQuery UI and friends)

Clear, type slowly enough to trigger the async search, wait for the menu, click the item by text.

```yaml
- { name: clear currency, selector: { id: "moneda" }, action: fill, value: "" }
- { name: type currency, selector: { id: "moneda" }, action: type, value: "{{ currency }}", delay: 30 }
- { name: menu appears, selector: "li.ui-menu-item", action: wait_for, state: attached, timeout: 6000 }
- name: pick currency
  action: click
  selector: { xpath: "//li[contains(@class,'ui-menu-item') and contains(.,'{{ currency }}')]" }
```

- `wait_for` replaces the `wait_after: 1500` sleep: it returns as soon as the menu exists, and fails loudly when the search returned nothing.

## Framework-bound text input (Angular, Vue, React)

`fill` dispatches one `input` event, which some two-way bindings ignore. Focus, select all, type
over the selection.

```yaml
- { name: focus amount, selector: { id: "importe" }, action: click }
- { name: select all, selector: { id: "importe" }, action: press, key: "Control+a" }
- { name: type amount, selector: { id: "importe" }, action: type, value: "{{ amount }}", delay: 30 }
```

- Key chords need `patchright` or `camoufox`; `nodriver`'s `press` handles named keys (`Enter`, `Tab`, `Escape`, `Backspace`, `Delete`, arrows) and single characters only.

## Reading a live input value

`dom` and `find` return markup, so a framework-bound `<input>` looks empty. `read` with `attribute: value` reads the DOM property instead.

```yaml
- name: read client fields
  selector: "#cp"
  action: read
  extract:
    cp: { attribute: value }
```


## Custom checkbox (hidden input, styled label)

A visually hidden `<input>` fails `check`'s actionability wait. Click the visible `<label>`, gated on the widget's state class so the step stays idempotent.

```yaml
- name: enable simplified isr
  selector: "label[for='0168']"
  action: click
  when:
    - { element_exists: { selector: "label[for='0168'] span.checkOff" } }
```

- With no state class, gate on `element_missing` for whatever the toggle reveals. A standard checkbox just takes `action: check` with `checked: true`.

## Dismissing a modal

Click only when the modal is actually up; `optional: true` covers the race where it self-closed.

```yaml
- name: dismiss modal
  selector: { xpath: "//div[contains(@class,'modal') and contains(@style,'block')]//button[contains(text(),'Aceptar')]" }
  action: click
  optional: true
  when:
    - { element_exists: { selector: ".modal.show" } }

- { name: modal gone, selector: ".modal-backdrop", action: wait_for, state: detached, timeout: 5000 }
```

- Keep it in its own `recovery_dismiss_modal.yaml` and reference it from the happy path as an `optional: true` `run-flow` step, so one file serves the flow and a manual rescue.

## Rotating-prefix ids

Sites that regenerate ids per deployment (`135textbox78` → `457textbox78`) keep the *suffix* stable. Probe the live id off one known element, then rewrite the map in one pass.

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

- Numeric-leading ids are not valid CSS ids: write `{ id: "135textbox78" }` (resolves to `[id="135textbox78"]`), never `#135textbox78`.
- Prefer a label-anchored XPath when one exists — it needs no healing: `{ xpath: "//label[contains(text(),'Copropiedad')]/following::select[1]" }`.

## Disambiguating same-text controls

Pages often carry several copies of a button, one visible.

```bash
llm-browser find --selector "//button[contains(text(),'Aceptar')]" --all
```

- Pick the copy with a unique id or attribute (`@entidad`, a semantic class), then confirm it is the live one with `wait_for` `state: visible` before clicking.

## Submit handlers that ignore real clicks

`dispatch: true` fires an untrusted DOM `click` — last resort, only for a JS-bound submit or confirm button. It sets `isTrusted=false`, which a detector can read (`camoufox` masks it; the Chromium drivers do not).

```yaml
- { name: continue, selector: "#btnContinuar", action: click, dispatch: true }
- { name: next screen, selector: "#confirmacion", action: wait_for, state: attached, timeout: 15000 }
```
