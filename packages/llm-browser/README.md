# llm-browser

Playwright-style browser automation with declarative YAML flows, designed for
LLM-driven agents: a typed Python API and a CLI over the same three drivers
(`patchright`, `camoufox`, `nodriver`), so an agent can drive a real browser
without touching Playwright/CDP directly.

## Architecture

A flow is loaded before it is run — every `run-flow` reference gets inlined
first, so the rest of the pipeline never touches disk or a store again:

```
source (file | text | store)
   │  FlowRepository.get(ref)      FileFlowRepository · DictFlowRepository · LayeredFlowRepository
   ▼
resolve_flow / resolve_flow_text   inline every run-flow child (async, the only I/O)
   ▼
load_flow_document / load_flow_text   pure pydantic validation → Flow
   ▼
run_flow(session, flow, data)
```

Running a flow steps down through four layers, each narrower than the one above:

```
Flow (pydantic)      steps: [GotoStep, ClickStep, WaitForStep, ReadStep, RunFlowStep(SubFlow)…]
   │  run_flow → execute_step (capture on failure, redact, outputs)
   ▼
actions              registry action name → fn(session, step) -> ActionResult      one per step type
   │
   ▼
BrowserSession       goto · find · wait_for_element · dom · probe · parse_elements · screenshot
   │  selector resolution, waits (waits.py), sanitization (html.py), probe JS, behavior pacing
   ▼
Driver (ABC)         resolve/count/first/is_visible/text_content · click/fill/type/press · goto/wait_for_load · evaluate · screenshot
   │  contract: no DOM waits (only wait_for_load blocks), trusted input, JS only in evaluate/is_visible/input_value/extract_rows
   ▼
patchright | camoufox | nodriver
```

- **Flow** — pydantic steps; owns templating and `when` conditions; never calls a driver.
- **actions** — registry mapping each step to session calls, one function per action.
- **BrowserSession** — selector resolution, waits, sanitization, probes; decides *how* to wait.
- **Driver (ABC)** — one abstraction over backends; only `wait_for_load` blocks; input must be trusted.
- **patchright / camoufox / nodriver** — concrete drivers; same five-rule contract, different backend.
- **session_input.py** — one click/fill/type/press/select_option/set_checked path every action and `BrowserSession` method shares; `tests/test_actions.py` asserts `actions.py`/`steps.py`/`flows.py` never touch `session.driver`.

Waiting: the five `wait_for` states are documented in [FLOWS.md](FLOWS.md#waiting).
Writing a driver: start from the contract in the `Driver` class docstring, `src/llm_browser/drivers/base.py` (details: [docs/DRIVERS.md](docs/DRIVERS.md)).

## Install

```bash
cd packages/llm-browser
uv sync
```

| Extra | Install | Adds |
|---|---|---|
| *(base)* | `uv sync` | `patchright` driver (Chromium) |
| `camoufox` | `pip install llm-browser[camoufox]` | `camoufox` driver (Firefox, fingerprint spoofing) |
| `nodriver` | `pip install llm-browser[nodriver]` | `nodriver` driver (Chromium via raw CDP) |

## Quickstart

```python
from llm_browser import BrowserSession

session = BrowserSession()
session.launch("https://example.com", headed=True)
# or reuse a browser you already started: session.attach("http://localhost:9222")

session.goto("https://example.com/login")
session.fill("#username", "admin")
session.click("button[type=submit]")

session.wait_for_element("#results", state="visible", timeout=10_000)

html = session.dom("body", max_depth=2, level="medium")

rows = session.parse_elements("tr.row", {
    "name": {"child_selector": "td.name", "attribute": "textContent"},
})

session.close()
```

```bash
llm-browser open --url https://example.com
llm-browser find --selector "#form"
llm-browser wait-for --selector "#results" --state visible --timeout 10000
llm-browser dom --selector "#content" --max-depth 2
llm-browser run --flow login.yaml --data '{"user": "admin"}'
llm-browser close
```

```yaml
params:
  - user

steps:
  - name: navigate
    action: goto
    url: "https://example.com/login"

  - name: fill user
    selector: "#username"
    action: fill
    value: "{{ user }}"
```

Flow patterns for hard widgets (autocomplete, framework-bound inputs, hidden checkboxes, rotating ids):
[docs/FLOW_PATTERNS.md](docs/FLOW_PATTERNS.md).

Authoring flows with Claude: `llm-browser skill install` drops a flow-authoring skill into
`.claude/skills/llm-browser-flows/SKILL.md` of the current repo (`--dest DIR` for another one);
`llm-browser skill show` prints it.

Re-enter a flow partway through with `llm-browser run --flow x.yaml --from <step name>` or
`run_flow(session, flow, data, from_step="...")`. See [FLOWS.md](FLOWS.md) for the full flow
language, and [docs/API.md](docs/API.md) for typed extraction (pydantic models, YAML-declared
schemas, the `parse` action) and the full session-method table.

## Waiting

`wait_for_element` / the `wait_for` step is the one wait — everything else (`find`, `find_all`,
`frame`, `element_exists`) goes through it too, so a state means the same thing everywhere. The
five states and their parameters: [FLOWS.md → Waiting](FLOWS.md#waiting).

## Drivers

| Driver | Stealth model | Notes |
|---|---|---|
| `patchright` (default) | removes Playwright automation fingerprints | Chromium; humanization via Playwright's helpers |
| `camoufox` | C++-level fingerprint spoofing | Firefox; stealth defaults on; the only viable **headless** option against strict detectors |
| `nodriver` | all writes go through trusted `Input.dispatch*` CDP events | Chromium via raw CDP; a few reads use JS (see docs/DRIVERS.md) |

Contract: see the `Driver` class docstring in `src/llm_browser/drivers/base.py`. Conformance
suite: `packages/llm-browser-conformance` (separate package, in progress). Full anti-bot
landscape, camoufox defaults and nodriver's detectable surfaces:
[docs/DRIVERS.md](docs/DRIVERS.md). Build-vs-buy investigation of the 2026
landscape, and why stealth is not the differentiator: [docs/RESEARCH.md](docs/RESEARCH.md).

## Attach, daemon, and capture modes

`attach` connects `llm-browser` to a Chromium you launched yourself and never kills it on
`close()`; `daemon` spawns and manages that Chromium for you. Full details — addressing a tab by
CDP target id, one-shot remote runs, the daemon caveat, single-process-vs-multi-invocation CLI
behavior: [docs/ATTACH.md](docs/ATTACH.md).

```bash
chromium --remote-debugging-port=9222 --user-data-dir="$HOME/.cache/llm-browser/attach-profile"
llm-browser attach --cdp-url http://localhost:9222
llm-browser daemon --url https://example.com   # or: manage Chromium yourself, see docs/ATTACH.md
llm-browser stop
```

```python
session = BrowserSession(driver="patchright")  # only patchright supports attach
session.attach("http://localhost:9222")
session.close()  # disconnects only — your Chromium keeps running
```

`BrowserSession(capture=...)` controls what's saved when a flow step fails: `"screenshot"`
(default), `"dom"`, or `"both"`. Paths and cleanup: [docs/API.md](docs/API.md#capture-modes).
