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

### Human-in-the-loop actions

Raise the tab, page a person, and wait for them to act. `notify` reads
its ntfy config from the environment:

| Variable | Description |
|----------|-------------|
| `LLM_BROWSER_NTFY_URL` | Full ntfy topic URL (e.g. `https://ntfy.sh/my-topic`). Required — without it `notify` fails with `NotifyError`. |
| `LLM_BROWSER_NTFY_TOKEN` | Optional bearer token for a protected topic. |
| `LLM_BROWSER_VNC_URL` | Optional default `Click` target for the notification — the console where a human can take over the browser. |

| Action | Params | Description |
|--------|--------|-------------|
| `notify` | `message` (templated), `title`, `priority` (1-5), `click` (URL, defaults to `LLM_BROWSER_VNC_URL`) | POST the message to the ntfy topic |
| `bring_to_front` | — | Raise the browser tab so a human at the console sees it |
| `wait_for` | `selector`, `until` (`present`/`absent`, default present), `timeout_ms` (default 30000, > 0), `poll_ms` (default 1000, > 0) | Probe the selector once, then poll until it matches `until` |

`wait_for` probes before sleeping, so a page that already satisfies
`until` returns immediately. Each poll tick is a `poll_ms` sleep plus one
short (500ms) probe, so the cadence is roughly `poll_ms`. On expiry it
raises `TimeoutError`, so the step fails like any other (or is skipped
with `optional: true`).

`bring_to_front` is best-effort: a driver that cannot surface a tab
(nodriver) prints a warning to stderr and the flow continues.

None of these three decide *whether* a human is needed — that is a
`when:` clause. Composed, they are the session watchdog
(`flows/session-check.yml`): raise the tab and page the owner only when
the logged-in marker is missing, then wait for it either way.

```yaml
- name: raise tab
  action: bring_to_front
  when: { element_missing: "{{ marker }}" }

- name: page owner
  action: notify
  when: { element_missing: "{{ marker }}" }
  message: "Login needed: {{ name }}"

- name: wait for login
  selector: "{{ marker }}"
  action: wait_for
  until: present
  timeout_ms: 1800000
  poll_ms: 5000
```

A healthy page skips both human-facing steps and clears the `wait_for`
on its first probe — nobody is woken.

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
| `run-flow` | `flow` (path), `data` (dict) | Run another flow inline as one step. `flow` resolves relative to the parent's directory (or absolute). `data` is templated, so the parent can pipe its own params into the child. The child's params are validated independently. |

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
