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

Every action, its own fields and their defaults: `reference/steps`.

A plain `click` whose error names an interception (`intercepts pointer events`)
is retried once with the target scrolled to the middle of the viewport, which is
what clears a fixed header or footer; the `try dispatch: true` hint is appended
only when that second try was intercepted too. Every other click failure — a
disabled control, a hidden one, a selector that matched nothing — is reported as
it happened, unretried. A driver that instead dispatches at the element's
coordinates without noticing the banner raises nothing, so there is nothing to
retry: that page still needs `dispatch: true`.

`fill` fires no keystroke at all when the session runs with humanization off
(or with `fill_as_type: false`): the value appears in one write, the equivalent
of a paste, and a page that watches input telemetry — masks, autocompletes,
hotkeys, bot scoring — sees nothing. Under a behavior YAML `fill_as_type`
defaults to `true`, so the same step types the value key by key. Prefer `type`
where that telemetry matters — it says what it does whatever the session is —
and a `delay: [min, max]` over a constant: a fixed cadence is itself a
fingerprint.

`humanize` switches the session's humanization on or off for one step: `true`
clicks on a curved path with a hover dwell, an in-box offset and a jittered
press even when the session runs with humanization off, `false` takes the plain
path even when it is on, and leaving it out follows the session. On `fill` it
switches `fill_as_type`: `true` types the value key by key on the humanized
cadence, `false` writes it in one go. `true` only switches on what is still
off: a knob the session tuned (a slower `type_char_delay`, a tighter
`click_offset_ratio`) is left as it was.

A driver's own opt-out is applied last, to whatever the step resolved to — a
`humanize`, a run-level `behavior=`, a `--behavior human`: camoufox leaves the
mouse path to its native engine, so none of them stacks ours on top unless the
session's own behavior YAML asked for it. The rate limit (`min_gap_ms`) is
never a humanization knob and survives either way; it is a jittered pause paid
before every step, not a floor measured from the last one, so an already slow
flow still waits it out.

`humanize: false` turns off the mouse path and the humanized pacing, not an
explicit `delay: [min, max]`: a pair you wrote is a cadence you asked for, so
the keys still land at a jittered interval. Drop the pair for a constant
cadence.

### Page actions (no selector)

`goto` takes `http(s)://` only; other schemes fail with `url must be http
or https` — opt out per call via `session.goto(url, allowed_schemes=(...))`
from Python. A `screenshot`, `download`, `read`, `parse` or `dom` step
returns its payload in `outputs` under the step name; `path:` only tells
`llm-browser run` where to write a copy, and the runner ignores it.

### Waiting

One step covers every kind of waiting: element presence, text stability, and
a page state only its rendered text names.

The states and what each one asks of the element: `reference/waits`.

`wait_for` takes a `selector`, a `text:`, or both — with neither it is rejected at
flow-load time. `text:` matches the whitespace-normalised `innerText` of the page
(or of whatever `selector` matches, when both are given), as a substring unless
`exact: true`, which asks some element's whole text to equal it. Accents, `&nbsp;`
and the text moving to a child node are all invisible to it, unlike an XPath
`contains(text(), …)`. A text wait reads `attached`/`visible` as "the text is
there" and `detached`/`hidden` as "it is gone"; the element-only states
(`enabled`, `disabled`, `stable`) are rejected. Only rendered text counts — a
`display:none` subtree reads as gone whether the wait is page-wide or scoped
to it, and a `selector` that matches nothing has no text, so it too reads as
gone. A scope that draws no box of its own but lays out what it
holds (`display: contents`) is worth exactly that — text it holds directly as
much as its rendered children.

`wait_for`: `timeout` (ms, default 3000, the whole poll budget — `timeout: 0` checks once), `interval` (ms, default 500, must be > 0), `settle` (ms, default 1500, `stable` only — `timeout` must exceed it, rejected at flow-load time otherwise). On timeout the step fails with `<selector> did not become <state> within <timeout>ms` (a text wait: `text '<text>' [inside <selector>] did not become present|absent within <timeout>ms`) plus whatever `BrowserSession(capture=)` asks for, in memory on the `FlowError`; `optional: true` turns that into a skip.

```yaml
- name: captcha appears
  selector: "iframe[title*='recaptcha' i]"
  action: wait_for
  state: visible
  timeout: 15000

- name: terms accepted
  selector: "#submit"
  action: wait_for
  state: enabled
  timeout: 10000

- name: modal is gone
  selector: ".modal-backdrop"
  action: wait_for
  state: detached
  timeout: 5000

- name: logged out
  action: wait_for
  text: "Sesión finalizada"
  timeout: 15000

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
| `read` | — | `extract` (see [below](#extract-spec-for-read-action)), `exclude`, `path` | Extract structured data as dicts. No `extract:`, `extract: {}`, or `extract: null` all read each match's own text as `text` — `read` on `body` gives `[{ text: … }]` |
| `parse` | `schema_path` | `path` | Like `read`, but rows come back as instances of the YAML-declared schema (see `api.md`) |
| `dom` | — | `max_depth` (default 0 = no limit), `level` (default `low`), `path` | Cleaned HTML snippet. `selector: body` returns the `<body>` element itself. `level` is the sanitization the CLI's `dom --level` and `session.dom(level=)` take: `low`, `medium`, `high`, `xhigh` (see [patterns.md → Reading the page](patterns.md#reading-the-page)). Several matches → the first in document order. |

### Composition

| Action | Required | Optional | Notes |
|---|---|---|---|
| `run-flow` | `flow` (reference or embedded flow) | `data` (dict, templated) | Runs another flow inline as one step |

`flow:` is a repository-resolved reference (a path, relative to the parent flow's own directory for the CLI, or absolute) or the child written inline as a `params:`/`steps:` mapping; references are inlined before validation, so a loaded `Flow` always carries its children. **Leaf-only**: a child may not itself contain `run-flow` steps (rejected while resolving). **`optional: true`** on the step swallows child failures instead of bubbling them. **`when:`** on the step is honored before the child is loaded. **Scope**: the child runs against the parent's params with `data:` merged over them, so a binding always wins over a parent param of the same name and an unbound parent param stays visible to the child.

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

### Repetition

One engine, two spellings: `repeat:` on a step is the modifier form below, and
[`action: repeat`](#the-block-form) with a `steps:` body is the same thing over
several steps. Both take the same sources (`over`, `over_selector`), the same
`on_error`, and both fill the same [report](#the-report).

`repeat: { over: <list>, as: <name> }` runs one step — any step, `run-flow`
included — once per item of a list in flow data: a param, a
[`save_as`](#saving-a-read-save_as), or the list written inline. Each pass binds
the item under `<name>` and its position under `<name>_index`, both usable in `{{ }}` anywhere
in the step, and keys its outputs `<step name>[<index>]` so passes never
overwrite one another. A step that writes a file (`screenshot`, `download`, or
any `path:`) gets the same index in its filename — `path: shots/page.png`
becomes `shots/page[0].png`, `shots/page[1].png` — so no pass overwrites
another's file. The `path:` itself is templated from the flow's params only, not
from `<name>`: the index is what makes each pass's file unique.

A `repeat` over a value that is not a list fails the step — a `FlowError`
carrying whatever the run collected before it — while a list param nobody
passed (an optional one, or one left out) runs zero passes and the flow moves
on. `as` must differ from `over`, rejected at flow load. A failure inside a pass
names the iteration: `FlowError.step` reads `row[3]`, while
`retry_hint.failed_step` stays the plain top-level name, since `--from` resumes
a step, not one of its passes.

```yaml
params: [codes]
steps:
  - name: row
    action: read
    selector: "#row-{{ code }}"
    repeat: { over: codes, as: code }
    extract:
      total: { child_selector: "td.total", attribute: textContent }
```

With `codes: [a, b]` that leaves `outputs` keyed `row[0]` and `row[1]`. A
repeated `run-flow` indexes the child's qualified keys the same way:
`each/row[0]`, `each/row[1]`.

#### The block form

`action: repeat` with a `steps:` body loops several steps. It is sugar: at flow
load it becomes exactly the modifier above on an inline `run-flow`, so both
spellings produce the same outputs and the same report.

```yaml
steps:
  - name: each
    action: repeat
    over_selector: tr.athing      # or: over: codes / over: [a, b, c]
    as: row
    on_error: skip                # default: stop
    steps:
      - { name: title, action: read, in: row, selector: .titleline a }
```

| Field | Meaning |
|---|---|
| `over` | the name of a list in flow data — a param or a [`save_as`](#saving-a-read-save_as) — or the list itself (`[a, b, c]`) |
| `over_selector` | a selector (`ref:` included); its match count is snapshotted when the step starts, without waiting — put a `wait_for` before the repeat when the rows load late, or it runs zero passes |
| `as` | what each pass binds: the item, or an element's text snippet (whitespace-collapsed, 80 chars max), plus `<as>_index` |
| `on_error` | `stop` (default) ends the run at the failing pass; `skip` keeps its partial outputs, names it in `skipped`, and goes on |
| `steps` | the body, at least one step |
| `when` | conditions checked per pass, before the body runs |

Rejected at flow load: both or neither of `over` / `over_selector`; an empty
`steps:`; a body step that is a `run-flow`, another `action: repeat`, or carries
a `repeat:` modifier; an `in:` that names anything but this repeat's `as`, sits
in a repeat that is not over elements, or names a step with no selector.

#### Addressing one element: `in:`

`in: <as>` scopes a step's selector to the current pass's element, descendants
only; a step without it addresses the page. The root selector is re-resolved and
re-indexed every pass, so no element handle outlives its pass, and a page that
dropped rows mid-loop fails that pass with `… matches N elements now, so element
I is gone` rather than reading the wrong row. A `read` under `in:` that matches
nothing fails its pass too — an empty row is a failure, not a clean pass. A
fallback selector (`primary` / `fallback`) cannot be scoped; name one selector.

#### The report

Every repeating step that ran is reported under `iterations`, on `FlowSuccess`
and `FlowError` alike, keyed by step name — a step that matched nothing reports
`total: 0` rather than nothing at all. `total` counts the passes that ran (after
`only`), `ok` those that succeeded, and `not_run` names the ones `stop` never
reached. Each entry of `failed[]` is one pass with what it takes to heal it: the
index and item it ran for, the inner step that failed, the error, message,
selector and hint, and the page's url and screenshot at that moment. `over`
names the list param the passes came from, and is `None` for an inline list
or an `over_selector`.

Under `stop` the report still carries the one failure that ended the run. A
repeating step written as a `repeat:` modifier inside a `run-flow` is reported
too, under its qualified name (`outer/grab`).

#### Running the unfinished passes again

When any pass failed, the result carries a `retry_hint` — on `FlowSuccess` too,
for an `on_error: skip` run. The rerun set is the failed passes **plus** the
ones `stop` never reached, in their original order. A repeat over a list **the
caller passed in** gets those items back in `retry_hint.data[<over>]`; rerunning
renumbers them from zero. Every other source — an inline list, an
`over_selector`, or a list the run saved or defaulted for itself — gets
`retry_hint.only = { <step>: [i, j] }` instead, which `run_flow(only=…)` and
`llm-browser run --only STEP=I,J` take — those passes run again under their
original indices, so the outputs line up with the first run's.
`retry_hint.failed_step` stays the top-level step name, since `--from` resumes a
step, not one of its passes.

`only` keys a step by its qualified name, the same way the report does, so
`--only outer/grab=1` reaches a repeating step inside a `run-flow`. When that
`run-flow` itself repeats, the key carries no outer index and so applies to
every pass of the outer loop.

### Saving a read (`save_as`)

`save_as` on a `read` step puts what it read into flow data: reachable in
`{{ }}`, `when:`, `repeat.over`, and a `run-flow` step's `data:`.

| Form | Saves | Fails when |
|------|-------|------------|
| `save_as: books` | Whole row list, as in `outputs` | Never — no rows saves `[]` |
| `{ name, field }` | `field` of row 0 | No row 0, or its `field` is null |
| `{ name, field, where }` | `field` of first row matching `where` | No row matches |

`where` is equality on extracted fields, compared as read — every extracted
value is a string, so quote numbers. A saved list with zero rows runs zero
`repeat` passes.

A save is local to the flow run that made it: a sub-flow sees its parent's
saves, but a save made inside a sub-flow never flows back to the parent. The
innermost binding wins — a `repeat` item, a `run-flow` `data:` key or a
sub-flow's own save hides an outer name of the same name inside its scope
only, leaving the outer value untouched. A skipped or `optional`-swallowed
read saves nothing, and `--from` past the read starts without it.

Rejected at flow load:

- a `save_as` name that is a declared param or another `save_as` of the same
  flow;
- a `path:` (the CLI names files after the run) naming a `save_as` of its own
  flow, or — inside a sub-flow — one of the parent's saves the `run-flow` step
  does not rebind;
- a step that uses a saved name before the step that saves it;
- `field` or a `where` key outside the step's `extract` fields;
- `where` without `field`;
- `save_as` on a step that also has `repeat`.

```yaml
steps:
  - { name: open category, action: goto, url: "https://books.toscrape.com/catalogue/category/books/travel_2/index.html" }
  - { name: books, action: read, selector: "article.product_pod h3 a", extract: { href: { attribute: href } }, save_as: books }
  - name: each book
    action: run-flow
    repeat: { over: books, as: book }
    flow:
      steps:
        - { name: open, action: goto, url: "https://books.toscrape.com/catalogue/category/books/travel_2/{{ book.href }}" }
```

`attribute: href` reads the attribute raw, often relative; prefix the base URL in the flow's `url:`.

## Loading flows

Getting from flow text to a result is three explicit stages; the repository is the only piece that differs between consumers:

```
source (file | text | store)
   │  FlowRepository.get(ref)
   ▼
resolve_flow / resolve_flow_text     inline every run-flow child (async, only I/O)
   ▼
load_flow_document / load_flow_text  pure validation → Flow, ref: selectors and all
   ▼
run_flow(session, flow, data, selector_map=…)   each ref: resolved as its step runs
```

- `FileFlowRepository(base_dir)` — filesystem; a relative ref reads under `base_dir`, absolute refs are honoured as-is.
- `DictFlowRepository(flows)` — flows already in hand, keyed by reference.
- `LayeredFlowRepository(*layers)` — first layer with the reference wins.

### Selector refs

A step names a selector symbolically with `ref: <group>.<name>` — at step level, under `selector:`, or in a `fields[]` / `read[]` entry — and the map is consulted per step at run time, not at load time. A flow full of refs therefore validates on its own; `selector_refs(flow)` names what it will ask for, and `missing_selectors(flow, map)` names what a map lacks, sub-flows included, sorted and unique:

```python
import asyncio
from pathlib import Path

from llm_browser.flow_pipeline import resolve_flow
from llm_browser.flow_repository import FileFlowRepository
from llm_browser.flows import load_flow_document, run_flow
from llm_browser.selector_map import (
    load_selector_map,
    missing_selectors,
    selector_refs,
)

repo = FileFlowRepository(Path("flows"))
flow = load_flow_document(asyncio.run(resolve_flow("invoice.yaml", repo)))
needed = selector_refs(flow)                                 # ['invoice.cp', 'invoice.rfc']
selector_map = load_selector_map(Path("selector_map.yaml"))  # or a dict from anywhere
missing = missing_selectors(flow, selector_map)              # [] before you run
result = run_flow(session, flow, {}, selector_map=selector_map)
```

- A map value is a selector in any accepted form: `{id: "x"}`, `{css: ".y"}`, or a plain string like `"text=Continue"`, which is used as the selector string.
- One map serves a run: a sub-flow's refs resolve from the same one.
- A ref the map lacks raises `MissingSelectorsError` (a `ValueError` carrying `.missing` and `.available`) as its step runs, so check `missing_selectors` first.
- `llm-browser run` and `llm-browser validate` take the map as `--selector-map PATH`. A flow with no `ref:` never reads that file; a path that is not there fails naming it; a ref the map lacks exits non-zero, naming every one of them under `missing_selectors`, before the browser is touched.

## Running, outputs, and redaction

`run_flow(session, flow, data, *, from_step=None, redact=(), behavior=None, selector_map=None)` runs a loaded `Flow` and never writes a file; pass `from_step=` to re-enter partway through. `FlowSuccess.outputs` (and a failing `FlowError.outputs`) holds every step result, keyed by step name (`"<run-flow step>/<step>"` inside a sub-flow): rows for `read`/`parse`, text for `dom`, a `BytesResult` (`name`, `content`, `media_type`) for `screenshot`/`download`. A step's `path:` is not consulted here — it is what `llm-browser run` writes under `--out-dir`; an embedding Python caller gets the value back and decides where, if anywhere, it goes.

`redact=[...]` (e.g. `redact=[pw]`) replaces each listed value with `***` in the retry hint, the error payload, `outputs`, `FlowError.dom`, and every log record emitted during the run.

`FlowSuccess.skipped` (and `FlowError.skipped`, for the skips collected before the failure) names every step the run passed over, in order, as `{ name, reason }` with the same qualified name `outputs` uses: a `when:` predicate that did not hold reads `when condition not satisfied`, and an `optional:` step whose action failed carries that failure. Without it a step that matched nothing is indistinguishable from one that ran, since both simply leave `outputs` alone.

A failing run also carries the page itself: `FlowError.screenshot` is PNG bytes and `FlowError.dom` is sanitized HTML text, both in memory and controlled by `BrowserSession(capture="screenshot" | "dom" | "both" | "none")`. `model_dump(mode="json")` base64-encodes the bytes and validating that back decodes them, so the result round-trips; `llm-browser run` instead writes both to `--capture-dir` and prints the paths.

### The run's behaviour

| knob | where | what it decides |
|---|---|---|
| `behavior=` | `run_flow(..., behavior=)`, `run_loaded_flow(..., behavior=)` | the run's humanization default: every step takes it unless it sets its own `humanize` |
| `--behavior` | `llm-browser run --behavior human\|off\|<behavior.yaml>` | the same default from the CLI; a path is loaded by the `behavior_config` schema |
| `FlowSuccess.behavior` | the result (`FlowError.behavior` too) | the profile the run used: `human`, `off`, or `custom` when a knob differs from both presets |

The session's own `Behavior` is left as it was — a run carries its behaviour, it does not leave it behind. The driver's opt-outs are applied last to it exactly as they are to a step's `humanize`, so `--behavior human` on camoufox still leaves the mouse path to the native engine.

### Capturing artifacts

| knob | where | default | what it decides |
|---|---|---|---|
| `capture` | `BrowserSession(capture=)` | `screenshot` | which of `screenshot` / `dom` a failing step attaches: `screenshot`, `dom`, `both`, `none` |
| `capture_level` | `BrowserSession(capture_level=)`, `llm-browser run --capture-level` | `high` | how hard the DOM snapshot is sanitized: `low`, `medium`, `high`, `xhigh` |
| `--capture-dir` | `llm-browser run` | the session dir | where the CLI writes `screenshot.png` and `dom.html` |

`high` drops every `src` and `href`, which is what you want for reading a page back. Use `medium` when the link is the point — where the flow would have gone next — and `xhigh` when you want the structure without the wrappers. The levels mean exactly what they mean for a `dom` step; see [patterns.md → Reading the page](patterns.md#reading-the-page).

## Selectors

| Format | Example |
|---|---|
| CSS string | `selector: "#btn"` |
| Attribute shorthand | `selector: { id: "x" }` → `[id="x"]` |
| Explicit CSS | `selector: { css: ".my-class" }` |
| XPath | `selector: { xpath: "//input[@name='q']" }` |

A CSS group (`main, article`) is handed to the browser as written: it matches every arm, in document order, never left to right. `read` and `parse` take the whole union — one row per match — `dom` reads the first match in document order, and every single-element step (`click`, `fill`, `screenshot: selector`) fails with `expected 1 element for '<selector>', found N` as soon as two arms match — unless the step's `pick` names which one to take ([below](#match-count-expect-and-pick)). The session API splits the same way: `find_all` returns the union, `find` raises on more than one match.

## Template variables

`{{ param_name }}` in any string value, resolved from flow data at runtime: `value: "{{ rfc }}"` with `params: [rfc]`. A missing name is left as written.

A dotted path indexes in — `{{ book.href }}`, `{{ books.0.href }}` — and fails the step if it resolves to nothing. Paths only, no expressions.

## Conditions

`when:` is a list of conditions, AND'ed: the step is skipped unless every one
holds, and the skip is named in `skipped` with `when condition not satisfied`.
They are checked when the step runs — once per pass inside a `repeat`, against
that pass's bindings — and on a `run-flow` step before the child is loaded.

| Condition | True when |
|---|---|
| `{ field: X, op: is_truthy }` | param `X` is truthy |
| `{ field: X, op: eq, value: V }` | param `X` equals `V` — `value:` is required; omitting it raises `KeyError` mid-run, not at load |
| `{ field: X, op: not_null }` | param `X` is not null |
| `{ element_exists: { selector: S } }` | `S` is present on the page |
| `{ element_missing: { selector: S } }` | `S` is absent from the page — the idempotent-toggle guard: only act when the post-action element isn't already there |
| `{ text_present: { text: T } }` | the page renders `T` — same matching as `wait_for`'s `text:`, with the same optional `selector` scope and `exact` |

## Step options

Every option, its type and its default: `reference/steps` — the shared
options at the end of that document, the per-action fields in each
section. What they *mean together* is the rest of this page.

### Match count: `expect` and `pick`

`expect` counts the matches and `pick` chooses among them — the types and
defaults are in `reference/steps`. What each combination does:

| `expect` | `pick` | Page has 1 | Page has 7 | Page has 0 |
|----------|--------|------------|------------|------------|
| `1` | none | runs | fails with the count | fails |
| `1` | `first` | runs | runs on the first match, warns | fails |
| `many` | none | runs | runs on every match | runs, zero rows |
| `many` | `last` | runs | runs on the last match | fails, `PickRangeError` |
| `many` | `9` | fails, `PickRangeError` | fails, `PickRangeError` | fails, `PickRangeError` |

An acting step (`click`, `fill`, …) drives one element, so an `expect` other
than `1` on it needs a `pick`. Both fields are rejected at flow load where they
could only be ignored: on `wait_for`, which waits for a state and not a count,
and on a `press` or `screenshot` with no selector, which matches nothing to
count. A failed count is a step error, under the run result's `data`:

```json
{
  "ok": false,
  "error": "MatchCountError",
  "message": "expected 1 element for 'p.price_color', found 7",
  "step_name": "price",
  "selector": "'p.price_color'",
  "hint": "tighten the selector, or add pick: first if the first match is the right one",
  "expected": 1, "found": 7,
  "samples": ["£45.17", "£51.33", "£37.59"]
}
```

A `pick` reaching past the matches is a `PickRangeError` instead — same shape,
no `expected`, and a message naming what the pick needed:
`pick: 9 needs at least 10 matches for 'p.price_color', found 7`.

A `pick` that took a count `expect` did not ask for runs, and says so in the
run's `warnings`:

```json
{
  "outputs": {"price": [{"text": "£45.17"}]},
  "warnings": [{"step": "price", "expected": 1, "found": 7, "picked": "first"}]
}
```

### What `timeout` bounds

`timeout` is the element wait only — how long the step looks for its target
before failing — not a ceiling on the step as a whole. It bounds a `read` or
`parse` wait too, but only when the step states a count (`expect:` an int, or
any `pick:`); a default `read` counts nothing and so waits for nothing. A
`type` step then costs roughly `len(value) × delay` on top of it, so a
2000-character value typed at `delay: 30` spends a minute *after* the wait
succeeded. Nothing in the library
cuts that short; an embedding server with its own per-call deadline (the MCP
tool timeout, a request handler) has to be given a budget that covers it, or
split the value across several steps.

## Extract spec (for `read` action)

```yaml
- name: read invoice
  selector: "tr.line-item"
  action: read
  extract:
    description: { child_selector: "td.desc", attribute: textContent }
    amount: { child_selector: "td.amount", attribute: textContent }
    link: "td.desc a@href"          # compact form
```

The readable properties, the compact `child selector@attribute` form and
the default field name are in `reference/extract`. Either way the value
comes back as a string, or `null` when the element or the value is
missing.

Leaving `extract` out entirely, `extract: {}`, and `extract: null` are all
that last form under the name `text`: one `{ text: … }` per matched element.

`exclude: [selector, …]` drops those matches from the text: `textContent`, `innerText`, `innerHTML`, `outerHTML` and `childElementCount` are read off a pruned copy of the element, so `read` on `body` can leave out a notification drawer or a `<select>` list. Attributes, `value` and `tagName` are untouched — they are the element's own, and no descendant is part of them — and the page itself is never modified. On a copy `innerText` has no layout, so under `exclude` it reads like `textContent`. A selector matching the read element itself is a no-op — only descendants are pruned, so `exclude: ["#card"]` on a `read` of `#card` drops nothing — and a `child_selector` still resolves on the live element, so a field whose element sits inside an excluded subtree is read, not lost.

```yaml
- name: read the article
  selector: "body"
  action: read
  exclude: ["nav", "aside", ".cookie-banner"]
```

The rows land in `FlowSuccess.outputs` under the step name; `path: <file>` on a `read` or `parse` step tells `llm-browser run` to JSON-dump them there as well.

## Patterns

Hard widgets — autocomplete, framework-bound inputs, hidden checkboxes, modal dismissal, rotating ids — have worked, JavaScript-free YAML in [patterns.md](patterns.md).

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

Every action reaches the browser through a `Driver` — the ABC in `llm_browser/drivers/base.py`, whose class docstring is the contract a backend implements. See "Writing a driver" in the llm-browser README, and [drivers.md](drivers.md) for stealth details.
