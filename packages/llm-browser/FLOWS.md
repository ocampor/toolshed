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
| `run-flow` | `flow` (path or loader key), `data` (dict) | Run another flow inline as one step. Loaded from a file (`load_flow`), `flow` resolves relative to the parent's directory (or absolute); loaded from text (`load_flow_text`), it resolves against the `subflows` mapping and then `subflow_loader`, never from disk. `data` is templated, so the parent can pipe its own params into the child. The child's params are validated independently. |

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

## Step outputs

`FlowSuccess.outputs` holds every `read` / `parse` / `dom` result, keyed
by step name (`"<run-flow step>/<step>"` inside a sub-flow); `read` /
`parse` as dicts, `dom` as its HTML string. Screenshots stay on disk.

```python
result = run_flow(session, flow, {})
result.outputs["headlines"]   # [{"title": "..."}, ...]
```

A step with `path:` still writes its file.

## Running flows

`run_flow(session, flow, data, *, from_step=None, redact=())` takes a
loaded `Flow` and never touches the filesystem;
`llm_browser.flow_files.run_flow_file(session, path, data, *,
selector_map=None, from_step=None, redact=())` loads a file and runs it,
setting `retry_hint.flow_path`. `run_flow` leaves that field empty —
re-run by passing the same model with `from_step=`.

`load_flow_text(text, subflow_loader=..., subflows=...)` parses a flow
from a YAML string. `run-flow` references are looked up in the `subflows`
mapping (ref → child YAML text) first, then handed to `subflow_loader`;
they are never read from disk. `subflow_refs(text)` lists a flow's
references without validating it, so an async caller can fetch every
child before calling `load_flow_text`. Bad YAML raises `ValueError`.

```python
from llm_browser.flows import load_flow_text, run_flow

flow = load_flow_text(yaml_text, subflow_loader=flows_by_name.__getitem__)
result = run_flow(session, flow, {"user": "bot"})
```

The CLI takes the flow as a file (`--flow PATH`), from stdin (`--flow
-`), or as a string (`--flow-yaml TEXT`) — exactly one of them, for both
`run` and `validate`:

```bash
llm-browser run --flow-yaml "$(cat flow.yaml)" --data '{}'
cat flow.yaml | llm-browser validate --flow -
```

## Redacting secrets

`redact` replaces each listed value with `***` in `retry_hint.data`,
`retry_hint.error`, the error payload, `outputs`, and every
`llm_browser` log record emitted during the run. Files written by
`path:` steps are not rewritten.

```python
run_flow(session, flow, {"password": pw}, redact=[pw])
```

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
