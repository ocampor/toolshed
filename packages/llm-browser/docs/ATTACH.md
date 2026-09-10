# Attach, Daemon, and Remote Runs

See [README → Attach, daemon, and capture modes](../README.md#attach-daemon-and-capture-modes)
for the essential commands. This page has the rest.

## Attach mode

Attach `llm-browser` to a Chromium you launched yourself (e.g. a day-to-day profile that's
already passed Cloudflare challenges). The remote browser is never killed on `close()` — only
the tab we opened and the CDP connection are released.

```bash
chromium --remote-debugging-port=9222 \
         --user-data-dir="$HOME/.cache/llm-browser/attach-profile"
```

```python
from llm_browser import BrowserSession

session = BrowserSession(driver="patchright")
session.attach("http://localhost:9222")
session.goto("https://chatgpt.com")
# ... interact ...
session.close()  # disconnects only — your Chromium keeps running
```

Only the `patchright` driver supports attach; others raise `NotImplementedError`.

## Addressing a tab by CDP target id

`attach` returns the `target_id` of the tab it opened. `(cdp_url, target_id)` is the full address
of that tab: pass both as global options and every command drives it — no `state.json`, so
parallel callers each own their tab and never land on someone else's.

```bash
llm-browser --cdp-url http://127.0.0.1:9223 attach          # -> {"target_id": "..."}
llm-browser --cdp-url http://127.0.0.1:9223 --target-id ABC goto --url https://example.com
llm-browser --cdp-url http://127.0.0.1:9223 --target-id ABC close
```

`close` here releases only that tab; the Chromium keeps running. If the tab was closed
meanwhile, commands fail with `Tab ABC not found`.

## One-shot remote run

`run --cdp-url` does the whole cycle in one command: attach to the running Chromium in a fresh
tab, run the flow, release the tab (the browser keeps running). The run is stateless and its tab
is addressed by target id, so several can run in parallel against the same Chromium.

```bash
llm-browser run --cdp-url http://127.0.0.1:9223 \
    --flow flows/warm-site.yml --data '{"url":"https://en.wikipedia.org"}'
```

## Automated detached spawn (`daemon`)

If you don't want to manage Chromium yourself but still need multi-CLI sessions, use the
detached-spawn helper. It launches Chromium in a new process group (survives Python exit) and
attaches over CDP in one step:

```bash
llm-browser daemon --url https://example.com
llm-browser goto --url https://example.com/page2
llm-browser screenshot
llm-browser stop          # actually kills the detached Chromium
```

```python
session = BrowserSession(driver="patchright")
session.launch_detached(url="https://example.com")
# ... later, even from another process:
session = BrowserSession(driver="patchright")
session.connect()          # reattaches via persisted CDP URL
# ... eventually:
session.stop_detached()    # kills the browser we spawned
```

**Caveat.** Daemon-spawned Chromium runs `connect_over_cdp`, which does not activate
patchright's stealth patches. Value comes from reusing a **warmed** profile across CLI calls —
log in / pass Cloudflare once in that profile and the browser carries cookies and TLS state
forward. For strict detectors, prefer the manual attach recipe above against a profile you've
warmed by hand.

## CLI: single-process vs multi-invocation

The `patchright` driver launches Chromium in-process (required for its stealth patches to
apply). That has one practical consequence for CLI use:

- **Launched mode is single-process.** `llm-browser open --url ...` then a follow-up
  `llm-browser screenshot` in a separate shell command will fail — Chromium died with the first
  Python process. Use `llm-browser run --flow x.yaml --url ...` to launch, run, and close
  end-to-end in one invocation. Or use the Python API.
- **Attach mode is multi-invocation safe.** Your Chromium keeps running between CLI calls, so
  `llm-browser attach --cdp-url ...` followed by any number of separate `llm-browser run` /
  `screenshot` / `close` commands works — each reconnects via the persisted CDP URL.

For long-running interactive sessions, use attach mode.

## Known warnings

Every browser launch prints one Node deprecation warning to stderr:

```
DeprecationWarning: `url.parse()` behavior is not standardized... (DEP0169)
    at .../patchright/driver/package/lib/utilsBundleImpl/index.js:8:4476
```

The call originates from patchright's vendored HTTP bundle (during CDP connect), not
llm-browser. It is harmless and upstream-tracked; do not suppress it with `NODE_NO_WARNINGS=1`
— it is the kind of signal we want surfaced if a future Node version turns it into an error.
Confirmed on patchright 1.58.2 (latest as of writing).
