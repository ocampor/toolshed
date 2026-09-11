# Flow Language Reference

For where flows sit in the library see the llm-browser README → Architecture. A flow is a YAML file describing a sequence of browser interactions.

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
```

## Actions

### Element actions (require `selector`)

| Action | Required | Optional | Notes |
|---|---|---|---|
| `click` | — | `dispatch` (bool, default false) | `dispatch: true` fires an untrusted DOM `click`, for overlays real input can't reach |
| `fill` | — | `value` | Clears the field, sets `value` |
| `type` | — | `value`, `delay` (ms, default 0) | Types character by character |
| `select` | — | `value` | Picks a `<select>` option |
| `check` | — | `checked` (bool, default true) | Sets checkbox state |
| `pick` | — | `value` | Clicks the list item matching this text |
| `press` | `key` | `selector` (omit to press the focused element) | Keyboard press |
| `download` | — | `path` | Triggers the download; the file's bytes come back in `outputs` under the step name. `path` names where `llm-browser run` writes it, and is ignored by the runner. With no `path`, `run` still writes it under `--out-dir`, using the filename the server suggested |

### Page actions (no selector)

| Action | Required | Optional | Notes |
|---|---|---|---|
| `goto` | `url` | `wait_until` (default `domcontentloaded`) | Since 0.8.0, `http(s)://` only; other schemes fail with `url must be http or https` — opt out via `session.goto(url, allowed_schemes=(...))` from Python |
| `screenshot` | — | `path` | The PNG bytes come back in `outputs` under the step name. `path` names where `llm-browser run` writes it, and is ignored by the runner. With no `path`, `run` still writes it under `--out-dir` as `<step name>.png` |

### Waiting

One step covers both kinds of waiting: element presence and text stability.

| State | True when | Notes |
|---|---|---|
| `attached` (default) | element is in the DOM | |
| `detached` | element is gone from the DOM | with a fallback selector, judged against whichever branch matched this tick |
| `visible` | element is rendered | |
| `hidden` | element is not rendered | |
| `stable` | text hasn't changed for `settle` ms | an element not there yet never settles |

`wait_for`: `timeout` (ms, default 3000, the whole poll budget — `timeout: 0` checks once), `interval` (ms, default 500, must be > 0), `settle` (ms, default 1500, `stable` only — `timeout` must exceed it, rejected at flow-load time otherwise). On timeout the step fails with `<selector> did not become <state> within <timeout>ms` plus whatever `BrowserSession(capture=)` asks for, in memory on the `FlowError`; `optional: true` turns that into a skip.

```yaml
- name: captcha appears
  selector: "iframe[title*='recaptcha' i]"
  action: wait_for
  state: visible
  timeout: 15000

- name: modal is gone
  selector: ".modal-backdrop"
  action: wait_for
  state: detached
  timeout: 5000

- name: isr recalculates
  selector: "#isr-total"
  action: wait_for
  state: stable
  settle: 800
  timeout: 20000
```

### Pacing actions (no selector)

| Action | Optional | Notes |
|---|---|---|
| `think` | `min_ms` (default 500), `max_ms` (default 2000) | Sleeps a random time in that range |
| `scroll` | `delta` (px/tick, default 600, negative scrolls up), `times` (default 1), `pause` (jitter ms, default 300-1200) | Mouse-wheels the page |

```yaml
- { name: read a bit, action: think, min_ms: 3000, max_ms: 8000 }
- { name: scroll down, action: scroll, delta: 500, times: 4 }
```

### Data actions

Every result comes back in `outputs`. `path:` is an instruction to `llm-browser run` — it writes that file under `--out-dir` once the run is over — and the runner itself ignores it. Rows and text with no `path:` stay inline in the JSON `run` prints; bytes are written either way, because base64 on stdout helps nobody.

| Action | Required | Optional | Notes |
|---|---|---|---|
| `read` | — | `extract` (see [below](#extract-spec-for-read-action)), `path` | Extract structured data as dicts |
| `parse` | `schema_path` | `path` | Like `read`, but rows come back as instances of the YAML-declared schema (see `docs/API.md` in the llm-browser package) |
| `dom` | — | `max_depth` (default 0 = no limit), `path` | Cleaned HTML snippet. Always sanitized at `low`; only the CLI's `dom --level` and `session.dom(level=)` pick another level (see [FLOW_PATTERNS.md → Reading the page](FLOW_PATTERNS.md#reading-the-page)) |

### Composition

| Action | Required | Optional | Notes |
|---|---|---|---|
| `run-flow` | `flow` (reference or embedded flow) | `data` (dict, templated) | Runs another flow inline as one step |

`flow:` is a repository-resolved reference (a path, relative to the parent flow's own directory for the CLI, or absolute) or the child written inline as a `params:`/`steps:` mapping; references are inlined before validation, so a loaded `Flow` always carries its children. **Leaf-only**: a child may not itself contain `run-flow` steps (rejected while resolving). **`optional: true`** on the step swallows child failures instead of bubbling them. **`when:`** on the step is honored before the child is loaded.

```yaml
# parent.yaml
params: [name]
steps:
  - name: setup
    action: run-flow
    flow: setup-form.yaml
    data: { username: "{{ name }}" }

  - { name: best-effort-cleanup, action: run-flow, flow: dismiss-popups.yaml, optional: true }
```

## Loading flows

Getting from flow text to a result is three explicit stages; the repository is the only piece that differs between consumers:

```
source (file | text | store)
   │  FlowRepository.get(ref)
   ▼
resolve_flow / resolve_flow_text     inline every run-flow child (async, only I/O)
   ▼
load_flow_document / load_flow_text  pure validation → Flow
   ▼
run_flow(session, flow, data)
```

- `FileFlowRepository(base_dir)` — filesystem; a relative ref reads under `base_dir`, absolute refs are honoured as-is.
- `DictFlowRepository(flows)` — flows already in hand, keyed by reference.
- `LayeredFlowRepository(*layers)` — first layer with the reference wins.

## Running, outputs, and redaction

`run_flow(session, flow, data, *, from_step=None, redact=())` runs a loaded `Flow` and never writes a file; pass `from_step=` to re-enter partway through. `FlowSuccess.outputs` (and a failing `FlowError.outputs`) holds every step result, keyed by step name (`"<run-flow step>/<step>"` inside a sub-flow): rows for `read`/`parse`, text for `dom`, and a `BytesResult` (`name`, `content`, `media_type`) for `screenshot`/`download`. A step's `path:` is not consulted here — it is what `llm-browser run` writes under `--out-dir`; an embedding Python caller gets the value back and decides where, if anywhere, it goes. `redact=[...]` (e.g. `redact=[pw]`) replaces each listed value with `***` in the retry hint, the error payload, `outputs`, `FlowError.dom`, and every log record emitted during the run.

A failing run also carries the page itself: `FlowError.screenshot` is PNG bytes and `FlowError.dom` is sanitized HTML text, both in memory and controlled by `BrowserSession(capture="screenshot" | "dom" | "both" | "none")`. `model_dump(mode="json")` base64-encodes the bytes and validating that back decodes them, so the result round-trips; `llm-browser run` instead writes both to `--capture-dir` and prints the paths.

### Capturing artifacts

| knob | where | default | what it decides |
|---|---|---|---|
| `capture` | `BrowserSession(capture=)` | `screenshot` | which of `screenshot` / `dom` a failing step attaches: `screenshot`, `dom`, `both`, `none` |
| `capture_level` | `BrowserSession(capture_level=)`, `llm-browser run --capture-level` | `high` | how hard the DOM snapshot is sanitized: `low`, `medium`, `high`, `xhigh` |
| `--capture-dir` | `llm-browser run` | the session dir | where the CLI writes `screenshot.png` and `dom.html` |

`high` drops every `src` and `href`, which is what you want for reading a page back. Use `medium` when the link is the point — where the flow would have gone next — and `xhigh` when you want the structure without the wrappers. The levels mean exactly what they mean for a `dom` step; see [FLOW_PATTERNS.md → Reading the page](FLOW_PATTERNS.md#reading-the-page).

## Selectors

| Format | Example |
|---|---|
| CSS string | `selector: "#btn"` |
| Attribute shorthand | `selector: { id: "x" }` → `[id="x"]` |
| Explicit CSS | `selector: { css: ".my-class" }` |
| XPath | `selector: { xpath: "//input[@name='q']" }` |

## Template variables

`{{ param_name }}` in any string value, resolved from flow params at runtime: `value: "{{ rfc }}"` with `params: [rfc]`.

## Conditions

Skip a step unless every condition holds (AND'ed).

| Condition | True when |
|---|---|
| `{ field: X, op: is_truthy }` | param `X` is truthy |
| `{ field: X, op: eq, value: V }` | param `X` equals `V` — `value:` is required; omitting it raises `KeyError` mid-run, not at load |
| `{ field: X, op: not_null }` | param `X` is not null |
| `{ element_exists: { selector: S } }` | `S` is present on the page |
| `{ element_missing: { selector: S } }` | `S` is absent from the page — the idempotent-toggle guard: only act when the post-action element isn't already there |

## Step options

| Option | Type | Description |
|--------|------|-------------|
| `name` | string | Step identifier (for logging and error messages) |
| `action` | string | One of the actions above |
| `optional` | bool | Swallow `TimeoutError`/`ValueError` from this step (and every child step for `run-flow`) and continue |
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
    description: { child_selector: "td.desc", attribute: textContent }
    amount: { child_selector: "td.amount", attribute: textContent }
```

Attributes: `textContent`, `value`, or any HTML attribute name. The rows land in `FlowSuccess.outputs` under the step name; `path: <file>` on a `read` or `parse` step tells `llm-browser run` to JSON-dump them there as well.

## Patterns

Hard widgets — autocomplete, framework-bound inputs, hidden checkboxes, modal dismissal, rotating ids — have worked, JavaScript-free YAML in [FLOW_PATTERNS.md](FLOW_PATTERNS.md).

**Autocomplete** — `type` to trigger the dropdown, `pick` to select from it:

```yaml
- name: type currency
  selector: { id: "currency_field" }
  action: type
  value: "US"
  wait_after: 1000

- { name: pick currency, selector: ".ui-menu-item:visible", action: pick, value: "USD - US Dollar" }
```

**Conditional click** — replace `click_if_exists`/`dismiss_modal` with `click` + `when`:

```yaml
- name: close popup
  selector: ".popup .close-btn"
  action: click
  when:
    - { element_exists: { selector: ".popup" } }
```

## Drivers

Every action reaches the browser through a `Driver` — the ABC in `llm_browser/drivers/base.py`, whose class docstring is the contract a backend implements. See "Writing a driver" in the llm-browser README, and [DRIVERS.md](DRIVERS.md) for stealth details.
