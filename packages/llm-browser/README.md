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
   │  FlowRepository.get(ref)
   ▼
resolve_flow / resolve_flow_text   inline every run-flow child (async, the only I/O)
   ▼
load_flow_document / load_flow_text   pure pydantic validation → Flow
   ▼
run_flow(session, flow, data, selector_map=…)   every ref: resolved per step (see `reference/steps`)
```

Running a flow steps down through four layers, each narrower than the one above:

```
Flow (pydantic)
   │  run_flow → execute_step
   ▼
actions
   │
   ▼
BrowserSession
   │
   ▼
Driver (ABC)
   │
   ▼
patchright | camoufox | nodriver
```

- **Flow** — pydantic steps; owns templating and `when` conditions; never calls a driver.
- **actions** — registry mapping each step to session calls, one function per action.
- **BrowserSession** — selector resolution, waits, sanitization, probes; decides *how* to wait.
- **Driver (ABC)** — one abstraction over backends; only `wait_for_load` blocks; input must be trusted.
- **patchright / camoufox / nodriver** — concrete drivers; same five-rule contract, different backend.
- **session_input.py** — the one input path every action and session method shares.

Writing a driver: start from the contract in the `Driver` class docstring, `src/llm_browser/drivers/base.py` (backend gaps: `src/llm_browser/drivers/__init__.py`).

## Install

```bash
cd packages/llm-browser
uv sync
```

The base install brings the `patchright` driver; the `camoufox` and `nodriver` extras
(`pip install llm-browser[camoufox]`) each add theirs — see
`[project.optional-dependencies]` in `pyproject.toml`.

## Quickstart

```python
from llm_browser import BrowserSession
from llm_browser.parse import parse_extract_spec

session = BrowserSession()
session.launch("https://example.com", headed=True)
# or reuse a browser you already started: session.attach("http://localhost:9222")

session.goto("https://example.com/login")
session.fill("#username", "admin")
session.click("button[type=submit]")

session.wait_for_element("#results", state="visible", timeout=10_000)

html = session.dom("body", max_depth=2, level="medium")

rows = session.parse_elements("tr.row", parse_extract_spec({"name": "td.name"}))

session.close()
```

```bash
llm-browser open --url https://example.com
llm-browser find --selector "#form"
llm-browser wait-for --selector "#results" --state visible --timeout 10000
llm-browser dom --selector "#content" --max-depth 2
llm-browser survey
llm-browser explore --selector ".result" --extract title=h3 --intent click
llm-browser explore --targets targets.yaml
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
[guide/patterns](src/llm_browser/docs/guide/patterns.md).

Authoring flows with Claude: the guidance lives in the env-sync `browser-flows` skill
([ocampor/env-sync](https://github.com/ocampor/env-sync), `claude/skills/browser-flows/`), which
env-sync installs globally and which reads them through `llm_browser.docs` (or the browser-api
`docs` tool). This package ships only the library docs.

The library never writes output files: every step result comes back in `FlowSuccess.outputs`,
and `llm-browser run` is the only thing that puts it on disk. A step's `path:` is written under
`--out-dir`. A `screenshot` or `download` that declared no `path:` is written there too, under
the name its payload came with (`shot.png`, the server's filename) — bytes are always written,
because base64 on stdout helps nobody. `read`, `parse` and `dom` results without a `path:` stay
inline in the JSON.

Re-enter a flow partway through with `llm-browser run --flow x.yaml --from <step name>` or
`run_flow(session, flow, data, from_step="...")`. See `reference/steps` for the full flow
language, `reference/extract` for typed extraction (pydantic models, YAML-declared schemas,
the `parse` action) and `reference/session` for every session method.

## Waiting

`wait_for_element` / the `wait_for` step is the one wait — everything else (`find`, `find_all`,
`frame`, `element_exists`) goes through it too, so a state means the same thing everywhere.
The states and their parameters: `reference/waits`.

## Drivers

`patchright` (default), `camoufox` and `nodriver`: which to pick, what each one spoofs and
where each one falls short is `src/llm_browser/drivers/__init__.py` and the driver class
docstrings, rendered into `reference/session`. The contract they implement is the `Driver`
class docstring, `src/llm_browser/drivers/base.py`. Build-vs-buy investigation of the 2026
landscape, and why stealth is not the differentiator: [docs/RESEARCH.md](docs/RESEARCH.md).

## Attach, daemon, and capture modes

`attach` connects `llm-browser` to a Chromium you launched yourself and never kills it on
`close()`; `daemon` spawns and manages that Chromium for you. Full details — addressing a tab by
CDP target id, one-shot remote runs, the daemon caveat, single-process-vs-multi-invocation CLI
behavior: the `llm_browser.cli` module docstring.

```bash
chromium --remote-debugging-port=9222 --user-data-dir="$HOME/.cache/llm-browser/attach-profile"
llm-browser attach --cdp-url http://localhost:9222
llm-browser daemon --url https://example.com   # or: manage Chromium yourself, see the `llm_browser.cli` docstring
llm-browser stop
```

```python
session = BrowserSession(driver="patchright")  # only patchright supports attach
session.attach("http://localhost:9222")
session.close()  # disconnects only — your Chromium keeps running
```

`BrowserSession(capture=...)` controls what a failing flow step carries back. Nothing is
written — `FlowError` holds it in memory, and `llm-browser run` is what puts it on disk
(`--capture-dir`). The modes: `reference/session`.

### Conformance

Real-browser check of every driver against a self-served fixture site: `packages/llm-browser-conformance` (separate package).

```bash
cd packages/llm-browser-conformance && uv sync --all-extras
uv run llm-browser-check                    # every installed driver
uv run llm-browser-check --driver nodriver --json
```

Run it after any change below `BrowserSession`. `FAIL` = contract violation, `skip` = API the driver does not implement, `xfail` = known gap listed in that package's README.
