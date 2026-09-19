# Python API Reference

See [README → Quickstart](../README.md#quickstart) for the short version. This page has typed
extraction, the full `BrowserSession` method table, and capture-mode details.

## Typed extraction

For Python callers who'd rather get coerced typed instances than dicts of strings, declare a
model with `ExtractField` defaults and use the classmethods on `ParseBase`:

```python
from llm_browser import BrowserSession
from llm_browser.parse import ExtractField, ParseBase


class Repo(ParseBase):
    name:  str = ExtractField(child_selector="h3 a")
    stars: int = ExtractField(child_selector=".stars")
    href:  str = ExtractField(attribute="href")  # off the row itself


session = BrowserSession()
session.launch("https://github.com/trending")
repos: list[Repo] = Repo.extract_all(session, "article.Box-row")
top:   Repo | None = Repo.extract_one(session, "article.Box-row")

assert isinstance(repos[0].stars, int)  # coerced from text
```

Pydantic handles validation and type coercion (`"42"` → `int 42`, `"true"` → `bool`, etc.). The
YAML `read` action keeps using the dict shape — pick whichever fits.

### From a YAML schema

If you'd rather declare the schema in YAML than in Python, point `build_model` at a schema file.
The returned class is indistinguishable from a hand-written `ParseBase` subclass — same
`extract_all` / `extract_one` call site.

```yaml
# schemas/repo.yaml
name: Repo
fields:
  name:
    type: str
    child_selector: "h3 a"
  stars:
    type: int
    child_selector: ".stars"
  description:
    type: str | None              # required → omit `default`; optional → declare it
    child_selector: ".desc"
    default: null
```

```python
from llm_browser.parse import build_model

Repo = build_model("schemas/repo.yaml")
repos = Repo.extract_all(session, "article.Box-row")
```

`type` strings are parsed against an allowlist, never evaluated; anything else raises
`ValueError: unsupported schema type: ...`. A given schema lives in *one* place — Python or
YAML, not both.

| Form | Accepted |
| --- | --- |
| Primitives | `str`, `int`, `float`, `bool`, `Decimal`, `date`, `datetime` |
| Optional | `X \| None`, `Optional[X]` |
| Containers | `list[X]`, `dict[str, X]` (nestable, e.g. `list[dict[str, str]]`) |

### From a YAML flow

The `parse` action uses the same schema — same shape as `read`, but rows come back as typed
schema instances instead of raw strings:

```yaml
- name: list_repos
  action: parse
  selector: "article.Box-row"
  schema_path: "schemas/repo.yaml"   # CWD-relative or absolute
```

`ParsedResult.rows` (`llm_browser.results.ParsedResult`) are `Repo` instances built from the
schema, values coerced by Pydantic — same outcome as `Repo.extract_all(session, ...)`. Empty
rows (every field `None`) come back as `None`, mirroring `read`'s behavior.

## Capture modes

`BrowserSession(capture=...)` controls what a failing flow step carries back on its
`FlowError` — in memory; the library writes no file:

| Mode | What `FlowError` carries |
|---|---|
| `"screenshot"` (default) | `screenshot`: PNG bytes of the failing page |
| `"dom"` | `dom`: the failing page's sanitized HTML, as text |
| `"both"` | both |
| `"none"` | neither |

`BrowserSession(capture_level=...)` decides how hard that DOM snapshot is
sanitized — a `SanitizeLevel` (`low`/`medium`/`high`/`xhigh`), default `high`.
`high` drops every `src` and `href`; `medium` keeps them, for when where the
page would have gone next is what you need. `llm-browser run --capture-level`
sets it, and `dom_snapshot(level=)` overrides it for one call.

`model_dump(mode="json")` base64-encodes `screenshot`; `run_flow(..., redact=[...])` scrubs
`dom` like every other text on the result. Persisting either is the caller's call —
`llm-browser run` does it, into `--capture-dir` (default: the session dir) as `screenshot.png`
and `dom.html`, and prints those paths in place of the base64.

The same rule covers step outputs. `llm-browser run` writes a step's `path:` under `--out-dir`;
a `screenshot` or `download` that declared none is written there anyway, under the name its
payload came with, because base64 on stdout helps nobody. Text and rows without a `path:` stay
inline in the printed JSON. Every written file is reported by its absolute path in place of the
value.

`<session_dir>` is `<state_dir>/sessions/<session_id>` (default `/tmp/llm-browser/sessions/default`)
and is logged at INFO on first `launch()` / `attach()`. It holds session *state*, never output:
`state.json` (how a detached browser is found again) and `user-data/`. The user-data-dir is
never auto-removed (profile reuse is intentional) — delete the session dir yourself to start
fresh.

## Session methods

| Method | Description |
|--------|-------------|
| `launch(url, headed)` | Launch Chrome and connect |
| `attach(cdp_url)` | Connect to an already-running Chromium over CDP |
| `attach_to_tab(cdp_url, target_id)` | Attach to one existing tab, addressed by its CDP target id |
| `launch_detached(url, headed)` | Spawn detached Chromium + auto-attach (multi-CLI safe) |
| `stop_detached()` | Kill a detached Chromium spawned by `launch_detached` |
| `close()` | Close session; attach/detached keep the browser alive |
| `connect()` | Reconnect to the browser recorded in the session state and return its page |
| `status()` | Whether a session is `open` or `closed`, with its CDP URL and target id |
| `goto(url)` | Navigate. `http`/`https` only by default; pass `allowed_schemes=("file",)` to opt a call in to another scheme |
| `find(selector)` | Find exactly one element (returns the driver's locator: a Playwright `Locator` on patchright/camoufox, a `NodriverLocator` on nodriver) |
| `click(selector, dispatch=False, humanize=None, behavior=None)` | Wait for the element, then click it — humanized mouse path when `Behavior.mouse_move`, which wheels the target into view, then re-checks what the pointer landed on and raises `ValueError` (`covered-after-move`, or `hit-test-failed` when the page could not be asked) rather than click something the path opened, answering the `HitTarget` (`tag`, `text`, `class_name`) it did click. `humanize=True`/`False` forces that path on or off for this call, `behavior=` runs it under a `Behavior` of your own. `dispatch=True` fires an untrusted DOM `click` event instead, for overlays real input cannot reach |
| `fill(selector, value, humanize=None, behavior=None)` | Set a field's value — cleared with select-all + Delete and typed character by character when `Behavior.fill_as_type`, otherwise a single `fill` (zero key events) |
| `clean(selector, behavior=None)` | Empty a field with trusted select-all + Delete; `ValueError` if anything is left |
| `type(selector, value, delay_ms=0, humanize=None, behavior=None)` | Type into a field. An explicit `delay_ms` is your own cadence and wins over the behaviour's per-key jitter — an `int` types at a constant rate, a `Jitter` becomes the per-key delay |
| `press(selector, key, behavior=None)` | Press `key` on the element; `selector=None` presses on whatever holds focus |
| `select_option(selector, value, behavior=None)` | Choose an option in a `<select>` |
| `set_checked(selector, checked, behavior=None)` | Check or uncheck a checkbox |
| `find_all(selector)` | Find all matching elements |
| `wait_for_element(selector, state=, timeout=, interval=, settle=)` | The one wait: polls from Python on a jittered `interval` until the element is `attached` / `detached` / `visible` / `hidden`, or `stable` — its text unchanged for `settle` ms, which is how you wait out streaming replies or a recalculating total. Raises `TimeoutError` naming selector, state and timeout. `timeout` is a real budget — sleeps are clamped to it and `timeout=0` checks once. No in-page script and no driver-native wait |
| `wait_for_text(text, selector=None, exact=False, state=, timeout=, interval=)` | The same wait for a landmark no selector names — a confirmation, an error toast. Polls the whitespace-normalised `innerText` of the page, or of everything `selector` matches; substring unless `exact`. `state` points it: `attached`/`visible` for there, `detached`/`hidden` for gone |
| `text_present(text, selector=None, exact=False)` | Whether that text is on the page right now — one read, no waiting, the bool half of `wait_for_text` |
| `element_exists(selector)` | Whether the element shows up within `timeout` — `wait_for_element(..., state="attached")` with the timeout read as `False` instead of raising |
| `pick(selector, value, behavior=None)` | Click list item matching text |
| `dom(selector, max_depth, level=)` | Cleaned HTML snippet; `level` is a `SanitizeLevel` (`low`/`medium`/`high`/`xhigh`). Several matches → the first in document order. |
| `parse_elements(selector, extract)` | Extract structured data |
| `explore(selector, extract=None, sample=3, timeout_ms=3000, intent=Intent.READ, sample_chars=200)` | Count and sample what a selector matches, and read the first one as a click would find it — an `ExploreResult`, never a click |
| `explore_many(targets, sample=3, sample_chars=200, timeout_ms=3000)` | The same answer for a list of `ExploreTarget`, from one page call and one wait — a list of `ExploreResult` in the order asked |
| `survey(max_items=60)` | What the page is made of before any selector is written: a `Survey` of landmarks, link shapes, repeats and hydration. Never clicks, never scrolls |
| `probe(selector=None, max_chars=)` | `PageProbe` of the page's human-attention signals in one evaluate; feed it to `probe.human_needed` |
| `evaluate(target, script)` | Run JS against a page or locator |
| `evaluate_document(script)` | Run a page-wide script against `<html>` — the evaluate path every driver awaits, which a script that waits needs |
| `download_file(selector, behavior=None, timeout=)` | Click the element and return what the browser downloaded as a `BytesResult` (`name`, `content`, `media_type`); `timeout` bounds both finding the element and waiting for the download. The payload is held whole in memory — there is no size ceiling — and `name` is the server's filename, so take its basename before writing it. Writing it anywhere is yours to do |
| `screenshot_bytes(selector=None)` | The current page as PNG bytes, or just `selector`'s element when one is given; nothing is written |
| `dom_snapshot(level=None)` | Sanitized HTML of the whole current page, as text; `level` defaults to the session's `capture_level` |
| `scroll(dx, dy, selector=None, behavior=None)` | Mouse-wheel scroll, over `selector` when given; each delta strays by up to `Behavior.scroll_delta_jitter` |
| `get_page()` | Raw driver page (a Playwright `Page` on patchright/camoufox, a nodriver `Tab` on nodriver) |
| `frame(selector)` | Enter iframe |
| `wait_for_load_state(state)` | Wait for page load |
| `latest_tab()` | Switch to newest tab |

### Which behaviour a call runs under

A call carries its behaviour; the session only holds the default it was built
with, and nothing a call does rewrites it. First row that applies wins:

| # | Source | Example |
|---|---|---|
| 1 | `behavior=` on the call | `session.click(sel, behavior=Behavior.human())` |
| 2 | `humanize=` on the call, or on the flow step | `session.click(sel, humanize=True)` |
| 3 | `behavior=` on the run | `run_flow(session, flow, {}, behavior=Behavior.off())` |
| 4 | the session's own `Behavior` | `BrowserSession(behavior=Behavior.human())` |

### Exploring before writing a step

A step written against a selector you have not checked fails on the run, not at
authoring time. `explore` answers it first — how many elements the selector
really matches, what they say, and whether the first of them is one a click or
a fill would land on:

```bash
llm-browser explore --selector ".result" --extract title=h3 --extract url="a@href" --intent click
```

```json
{"count": 24,
 "sample": [{"title": "First", "url": null}, {"title": "Second", "url": null}],
 "empty_fields": ["url"], "text_chars": 1840,
 "first": {"tag": "a", "text": "First", "name": "First", "href": "/1",
           "visible": true, "enabled": true, "in_viewport": true,
           "hit_tested": true, "stable": true, "pointer_events": true,
           "clickable": true, "why_not": []},
 "since_navigation_ms": 620, "since_call_ms": 41,
 "candidates": ["#first-result", "a[href^=\"/results/\"]"],
 "stability": "other", "verdict": "ok"}
```

| Field | What it answers |
|---|---|
| `count` / `sample` / `empty_fields` / `text_chars` | How many matched, what the first `sample` of them say under `extract`, which fields no sampled row filled in (a wrong child selector, or a page still hydrating), and how much rendered text they carry |
| `first` | The first match as a click would find it, `null` when nothing matched |
| `first.why_not` | Empty, or only `offscreen`, exactly when `clickable`; one or more of `hidden`, `disabled`, `covered`, `offscreen`, `moving`, `no-pointer-events`, `not-interactive` |
| `first.enabled` | The platform's own `:disabled`, so a control the `<fieldset>` around it disabled reads as disabled |
| `first.covered_by` | The `tag` and `text` of whatever sits over the element's centre — never the element itself, a descendant, an ancestor (the centre fell in a gap in its own box) or the control a `label` around that point labels |
| `first.hit_tested` | Whether the centre was a point the page could be asked about — `false` for a box of no size, or a centre still outside the viewport after the scroll, where `covered_by` is "not asked" rather than "nothing over it" |
| `first.stable` | Whether two rects 100 ms apart are the same box — an element still animating is one a click lands beside |
| `first.nested_controls` | Up to five `button`/`a`/`input` inside the match — what a loose click lands on instead of the match itself |
| `since_navigation_ms` | How long the page had been up when the first match was read, off the page's own clock; `null` on timeout. A `wait_for` timeout of 3x this (minimum 3000) is the measured number |
| `since_call_ms` | The same wait measured from the call, which on a page that loaded seconds ago says only how fast this call was |
| `error` | Why this target was never explored — `not css` for a selector the page refused to parse. Absent when the answer came from the page |
| `candidates` | Up to three sturdier selectors — a `data-testid` on the match or an ancestor within three levels, an aria label or role+name, an ungenerated id, a link's section (`a[href^=…]`), a hashed class — one per kind and the best three checked to match that element and nothing else (or, for `--intent read`, the same number of rows the explored selector found — a candidate matching one of thirty rows is not a selector for the list). Interpolated values are escaped; `role=…` is Playwright's own syntax and is proposed only to drivers that parse it |
| `stability` | What the selector you wrote leans on: `data-testid`, `aria`, `id`, `class-hash`, `positional`, `other` |
| `verdict` | `ok`, `ambiguous`, `missing` or `not_actionable`, against `--intent` (`read` default, or `click` / `fill` / `wait`) |

`first.clickable` is `why_not` being empty bar `offscreen`, which every driver
handles by scrolling before it clicks — and which `explore` does itself, so the
hit test has an answer: exploring never clicks, but it may scroll the viewport.
Each sampled field is cut to `--sample-chars` (200); reading a row whole is what
`read` is for.

The command exits non-zero unless the verdict is `ok`, and drops null fields
from its JSON like every other one — `role`, `aria_label` and `covered_by` are
absent above. Nothing here is a flow step: it is for writing the step, not for
running it.

### A page's worth of selectors in one call

`explore` per selector is one wait per selector, and a page is usually eight of
them. `explore_many` asks them together: one page evaluation counts, samples
and first-match-reads every target, and the wait ends when the **first** of
them appears — so the selector that is simply not there costs nothing rather
than another full timeout.

```bash
llm-browser explore --targets targets.yaml
```

```yaml
# targets.yaml — one entry per selector, in the order the answers come back
- selector: ".athing"
  extract: { title: ".titleline > a", url: ".titleline > a@href" }
- { selector: ".morelink", intent: click }
- { selector: "#searchInput", intent: fill }
```

Each answer is the same `ExploreResult` as `explore`, with the same fields and
the same `verdict` against that target's own `intent`; the command exits
non-zero unless **every** verdict is `ok`. Candidates are still verified from
Python — at most three counts per target — because a proposal nothing checked
is not a candidate.

`--extract` and `--intent` belong to a target rather than to the batch, so
passing either alongside `--targets` is a usage error rather than a flag that
quietly means nothing; `--sample`, `--sample-chars` and `--timeout` apply to
the whole batch.

Two things differ from `explore`. Selectors are CSS (the page is asked with
`querySelectorAll`) — no XPath, no selector-map alias — and one the page cannot
parse is that target's own answer, `count: 0`, `verdict: missing` and
`error: "not css"`, never the batch's exception: the other targets were read in
the same page call and are worth keeping. And `since_call_ms` is measured in the
page, from the start of the batch, so every target shares the one wait.

What the batch costs: the wait, plus 100 ms of settle per target (each
first-match read waits for its element to stop moving), all inside one
`evaluate` the driver is given that long plus a margin — so a `--timeout 45000`
is the wait it says it is rather than a driver timeout at 30 s. That per-target
cost is why a batch takes **at most 20 targets**; more is a usage error, not a
page call nobody sized.

### Surveying before exploring

`survey` is the call before the first selector: it reads what the page offers
rather than checking what you guessed.

```bash
llm-browser survey
```

```json
{"title": "Hacker News", "url": "https://news.ycombinator.com/",
 "hydration": {"since_navigation_ms": 840, "ready_state": "complete"},
 "landmarks": [{"selector": "[data-testid=\"grid\"]", "tag": "main", "text": "Top stories", "count": 1}],
 "link_shapes": [{"shape": "item?<query>", "selector": "a[href^=\"item\"]", "count": 60}],
 "repeats": [{"selector": "tr.athing", "count": 30,
              "nested_controls": [{"tag": "a", "text": "upvote"}]}],
 "truncated": false}
```

| Field | What it answers |
|---|---|
| `landmarks` | Up to `max_items` elements that carry a name, deduped by selector and best first: a test id, then an aria label, then an ungenerated id, then a bare role. `count` is how many elements answer to **that selector** page-wide — `1` means it is already a step's worth, and a `2` is the `ambiguous` you would otherwise meet at run time |
| `link_shapes` | Hrefs grouped by the section they point at rather than the page: `/mission/<id>` ×41, with the `a[href^=…]` that selects the family. Busiest first |
| `repeats` | The structures the page uses more than twice — cards, rows, items — as the selector every member answers to, how many there are, and the controls inside one of them. This is the card detector: the `count` is the number a `read` is about to return. Siblings are grouped by tag and by **every** class they share, so a news table reads as `tr.athing` ×30 rather than `tbody > tr` ×96, and two components that merely share a utility class stay two entries (`div.flex.rounded`, `div.flex.border`) rather than one `div.flex` that is neither. A run you can click into ranks above one you cannot, which ranks above a bigger one with no class of its own — a page's cards before the hundred syntax spans of its code sample |
| `truncated` | True when the page outgrew a raw cap, so the lists are a sample of it rather than all of it: narrow the page (or survey a frame) rather than trust the answer |
| `hydration` | `since_navigation_ms` off the page's own clock and `document.readyState` — the two numbers a `wait_for` timeout is sized from |

A repeat is named by the classes every member carries, preferring the ones the
build did not number (`.tile` over `.sc-card-0-2-1`); with no such class it is
named by what holds it (`[data-testid="deck"] > article`). Every list is capped
by construction — lists are truncated, never the fields inside them — so a page
of ten thousand elements answers in the same breath as a page of ten, and
`truncated` says when that happened.

Two page calls, not one: the first reads the page, the second counts what each
selector the first named matches. So every `count` is the number that selector
is about to return — `tbody > tr` says 96 even where the run it was spotted in
was 30 — rather than the size of the run or the rank that named it.

