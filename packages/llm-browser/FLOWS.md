# Flow Language Reference

A flow is a YAML file that describes a sequence of browser interactions.

## Structure

```yaml
params:
  - rfc                                          # required param
  - { region: { required: false, default: MX } } # optional with default

steps:
  - name: navigate
    action: goto
    url: "https://example.com/form"

  - name: fill name
    selector: "#name"
    action: fill
    value: "{{ rfc }}"

  - name: submit
    selector: "button[type=submit]"
    action: click
```

## Actions

### Element actions

Require a `selector` to identify the target element.

| Action | Params | Description |
|--------|--------|-------------|
| `click` | — | Click the element |
| `fill` | `value` | Clear field and set value |
| `type` | `value`, `delay` (ms, default 0) | Type character by character |
| `select` | `value` | Pick a `<select>` dropdown option |
| `check` | `checked` (bool, default true) | Set checkbox state |
| `pick` | `value` | Click the list item matching this text |

### Page actions

No selector needed.

| Action | Params | Description |
|--------|--------|-------------|
| `goto` | `url`, `wait_until` (default domcontentloaded) | Navigate to URL |
| `wait` | `state` (domcontentloaded, load, networkidle), `timeout` (ms) | Wait for page load state |
| `screenshot` | `path` (optional) | Take a screenshot. Without `path`, writes to the session's default location and returns the path. With `path`, writes to that path (parent dirs created). |

### Pacing actions

Human-like idling. No selector needed.

| Action | Params | Description |
|--------|--------|-------------|
| `think` | `min_ms` (default 500), `max_ms` (default 2000) | Sleep a random time in that range |
| `scroll` | `delta` (px per wheel tick, default 600, negative scrolls up), `times` (default 1), `pause` (`min_ms`/`max_ms` jitter between ticks, default 300-1200) | Mouse-wheel the page |

```yaml
- name: read a bit
  action: think
  min_ms: 3000
  max_ms: 8000

- name: scroll down
  action: scroll
  delta: 500
  times: 4
```

### Data actions

Return data. Pair with `path:` (where supported) to land artifacts on
disk mid-flow.

| Action | Params | Description |
|--------|--------|-------------|
| `read` | `extract` (see below) | Extract structured data from elements |
| `dom` | `max_depth` (default 0 = no limit), `path` (optional) | Return cleaned HTML snippet. When `path` is set, writes the same HTML to that path (parent dirs created) AND still returns it inline. |

### Composition

| Action | Params | Description |
|--------|--------|-------------|
| `run-flow` | `flow` (path or loader key), `data` (dict) | Run another flow inline as one step. `flow` resolves relative to the parent's directory (or absolute); when the flow was loaded with `load_flow_text(..., subflow_loader=...)`, a reference that isn't an existing file is passed to that loader instead. `data` is templated, so the parent can pipe its own params into the child. The child's params are validated independently. |

#### Sub-flow constraints

- **Leaf-only**: a flow referenced by `run-flow` may not itself contain
  `run-flow` steps. Nested sub-flows are rejected at child-load time.
- **`optional: true` on the `run-flow` step** swallows child failures —
  the parent advances to the next step instead of bubbling the error.
- **`when:`** is honored on the `run-flow` step itself; if the
  condition fails, the child is never loaded.

```yaml
# parent.yaml
params:
  - name

steps:
  - name: setup
    action: run-flow
    flow: setup-form.yaml
    data:
      username: "{{ name }}"

  - name: best-effort-cleanup
    action: run-flow
    flow: dismiss-popups.yaml
    optional: true
```

## Capturing artifacts mid-flow

To save HTML or screenshots from inside a flow without pausing
execution, use the `path:` field on `dom` and `screenshot`. This is
the right tool for capture-and-continue patterns (e.g., snapshotting
a conversation turn, then continuing to the next step).

```yaml
- name: save turn
  action: dom
  selector: "[data-testid='conversation-turn']"
  path: "{{ out_dir }}/turn.html"

- name: save reply screenshot
  action: screenshot
  path: "{{ out_dir }}/screenshot.png"
```

To capture multiple disjoint elements, target their nearest common
wrapper with one `dom` step rather than running N separate captures.

## Step outputs in memory

Every `read`, `parse` and `dom` step also hands its result back to the
caller: `run_flow` returns a `FlowSuccess` whose `outputs` dict is keyed
by step name (`"<run-flow step>/<step>"` for steps inside a sub-flow).
`read` / `parse` rows come back as dicts, `dom` as its HTML string.

```python
result = run_flow(session, "flow.yaml", {})
result.outputs["headlines"]   # [{"title": "..."}, ...]
```

`path:` is unchanged and orthogonal: a step with `path:` writes its file
*and* returns its value. Screenshots stay on disk — `outputs` never
holds image bytes.

## Running flows without touching disk

`load_flow_text(text, subflow_loader=...)` parses a flow from a YAML
string. Sub-flow references that aren't existing files are handed to
`subflow_loader`, which returns the child's YAML text, so a whole flow
tree can come from a database, an HTTP payload, or an LLM:

```python
from llm_browser.flows import load_flow_text, run_flow

flow = load_flow_text(yaml_text, subflow_loader=flows_by_name.__getitem__)
result = run_flow(session, flow, {"user": "bot"})
```

`run_flow` takes either a path or a loaded `Flow`. When it gets a model
there is no path to point back at, so `retry_hint.flow_path` is empty —
re-run by passing the same model with `from_step=`.

## Redacting secrets

Values injected through `data` can be scrubbed from everything the
runner hands back:

```python
run_flow(session, flow, {"password": pw}, redact=[pw])
```

Each listed value is replaced by `***` in `retry_hint.data`,
`retry_hint.error`, the failing step's error payload, `outputs`, and any
`llm_browser` log record emitted while the flow runs. Files written by
`path:` steps are *not* rewritten — don't point `path:` at a page that
renders a secret.

## Selectors

Steps accept selectors in these formats:

```yaml
selector: "#btn"                    # CSS selector (string)
selector: { id: "135textbox32" }    # Attribute: [id="135textbox32"]
selector: { css: ".my-class" }      # Explicit CSS
selector: { xpath: "//input[@name='q']" }  # XPath
```

## Template variables

Use `{{ param_name }}` in any string value. Resolved from flow params at runtime.

```yaml
params: [rfc, amount]
steps:
  - name: fill rfc
    selector: { id: "rfc_field" }
    action: fill
    value: "{{ rfc }}"
```

## Conditions

Skip a step unless conditions are met. All conditions are AND'ed.

```yaml
# Skip unless param is truthy
when:
  - { field: "extra_data", op: "is_truthy" }

# Skip unless param equals value
when:
  - { field: "mode", op: "eq", value: "fast" }

# Skip unless param is not null
when:
  - { field: "cp", op: "not_null" }

# Skip unless element exists on page
when:
  - { element_exists: { selector: "#popup" } }
```

## Step options

| Option | Type | Description |
|--------|------|-------------|
| `name` | string | Step identifier (for logging and error messages) |
| `action` | string | One of the actions above |
| `optional` | bool | Swallow `TimeoutError`/`ValueError` from this step (and from all child steps when `action: run-flow`) and continue |
| `selector` | string or dict | Target element (required for element/data actions) |
| `when` | list | Conditions to evaluate before executing |
| `wait_after` | int (ms) | Sleep after step completes |
| `eval` | string | JavaScript to evaluate on page (independent of action) |

## Extract spec (for `read` action)

```yaml
- name: read invoice
  selector: "tr.line-item"
  action: read
  extract:
    description:
      child_selector: "td.desc"
      attribute: textContent
    amount:
      child_selector: "td.amount"
      attribute: textContent
    code:
      child_selector: "input.code"
      attribute: value
```

Attributes: `textContent`, `value`, or any HTML attribute name.

Set `path: <file>` on a `read` or `parse` step to JSON-dump the rows to
disk — the only way to surface row data back to the caller, since the
flow runner only returns `FlowSuccess(step=name)` and otherwise drops
action results.

## Autocomplete pattern

Use `type` to trigger the dropdown, then `pick` to select from it:

```yaml
- name: type currency
  selector: { id: "currency_field" }
  action: type
  value: "US"
  delay: 50
  wait_after: 1000

- name: pick currency
  selector: ".ui-menu-item:visible"
  action: pick
  value: "USD - US Dollar"
```

## Conditional click pattern

Replace `click_if_exists` or `dismiss_modal` with `click` + `when`:

```yaml
- name: close popup
  selector: ".popup .close-btn"
  action: click
  when:
    - { element_exists: { selector: ".popup" } }
```
