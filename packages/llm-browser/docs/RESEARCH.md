# Build vs Buy: the browser-automation landscape

Investigation of 2026-09-10 — is `llm-browser` + `browser-api` adding value, or rebuilding what
exists? Code read at `llm-browser`, `browser-api` and `facturacion-sat/flows`; third-party claims
are linked, and anything unconfirmed is marked UNVERIFIED.

## Verdict

Hybrid: keep owning the flow/guardrail layer and the HTTP/MCP boundary, and stop treating the
stealth driver layer as a differentiator. The 2026 evidence says fingerprint stealth buys a few
percent while behavioral telemetry separates every agent architecture at F₁ ≈ 0.999, so the layer
with the highest maintenance cost is the one that no longer decides outcomes. Buy the transport;
keep the constraints — no product on the market encodes negative constraints ("do everything up to
but excluding the last button").

## Comparison

"LLM drive": **NL** = natural-language actions, **Steps** = explicit deterministic calls. "CDP
attach" = can it attach to *our* already-running warmed Chrome over LAN.

| Tool | What it is | LLM drive | Stealth model | HITL | CDP attach | License / maturity |
|---|---|---|---|---|---|---|
| **llm-browser** (ours) | Python library | Steps (YAML) | Injects JS on `read`/`parse`/`dom`/probe; CDP-synthetic input | `human_needed` flag, no resume | Yes (`connect_over_cdp`) | Private; 606 tests, no real-browser test |
| **browser-api** (ours) | FastAPI + MCP | Steps (15 tools, no click/fill/type outside a flow) | Inherits llm-browser | `human_needed` + `vnc_url` + polling | Attach-only, never launches | Private; 104 tests, no live-browser test |
| [Playwright MCP](https://github.com/microsoft/playwright-mcp) | MCP server + Chrome extension | Steps (~24 tools) | Zero stealth by design; `browser_snapshot` runs an [injected script](https://github.com/microsoft/playwright/blob/main/packages/injected/src/ariaSnapshot.ts) | None first-class | **Yes** — `--cdp-endpoint` | Apache-2.0, $0; 37.0k★, v0.0.80 |
| [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp) | MCP server, Google-maintained | Steps | None; Puppeteer-based | None | **Yes** — `--browserUrl` | Apache-2.0, $0; 51.6k★, v1.9.0 |
| [Stagehand v4](https://github.com/browserbase/stagehand) | SDK + MV3 extension engine | Both | Extension at `document_start`, `"world":"ISOLATED"` | Live View; no pause/resume; `agent()` removed in v4 | v3 yes; v4 needs its extension resident (UNVERIFIED) | MIT + cloud $20–99/mo; two breaking rearchitectures in ~12 mo |
| [Browser Use](https://github.com/browser-use/browser-use) | Python library + cloud + MCP | NL | CDP-native; `getEventListeners()` leak; `highlight_elements=True` by default; [no local stealth](https://github.com/browser-use/browser-use/issues/3074) | `agent.pause()`/`resume()`; no ask-human tool | **Yes** — `cdp_url`; not via its MCP | MIT; 114.1k★; four incompatible browser APIs in <2 yrs |
| [Skyvern](https://github.com/Skyvern-AI/skyvern) | Self-hostable server + cloud + MCP | Both | Injects [`domUtils.js`](https://github.com/Skyvern-AI/skyvern/blob/main/skyvern/webeye/scraper/domUtils.js); anti-bot/proxy/captcha **cloud-only** | **Human Interaction block** — pause, approve, resume (≤300 min) | **Yes** — [`cdp-connect`](https://www.skyvern.com/docs/developers/self-hosted/browser) | **AGPL-3.0**; 23.0k★, weekly releases |
| [Browserless](https://github.com/browserless/browserless) | Self-hostable pool + BrowserQL | Both | CDP-level stealth routes; humanized cadence (trusted input UNVERIFIED) | Best resume story — `liveURL` → resume on `liveComplete` | No (inverse direction only) | SSPL-1.0 or commercial; 13.7k★ |
| [Anthropic computer use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool) | Tool schema, you run the executor | NL over screenshots | `xdotool` OS-level input — no CDP, no injected script; the only architecture not shown to be caught | None built in | No (screen-level) | Executor MIT; ~4,500 tok/req overhead |
| [patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python) | Playwright fork | n/a | Avoids `Runtime.enable`, flag cleanup, closed shadow roots; CDP-synthetic input | n/a | API exists; patches under `connect_over_cdp` UNVERIFIED (our docstring says they do not survive) | Apache-2.0; bus factor 2, active |
| [Camoufox](https://github.com/daijro/camoufox) | Custom Firefox build | n/a | C++-level interception; **trusted-path input** — the only trusted-input option | n/a | No — Juggler, not CDP | MPL-2.0; still beta, bus factor 1, admitted 1-yr gap |
| [nodriver](https://github.com/ultrafunkamsterdam/nodriver) | Raw CDP library | n/a | No WebDriver binary; 0 blocked in the one independent benchmark, but Brotector lists it detected | n/a | **Yes** | **AGPL-3.0**; 0.50.3 (2026-05-13), ~4 mo silent, bus factor 1 |

## Q1 — Does anything give us ≥80% of the differentiators, self-hosted, attach-capable, with handoff?

- No. [Skyvern](https://github.com/Skyvern-AI/skyvern) is closest at ~60–70% and the only credible target.
- It is the sole self-hostable product that attaches to an existing remote Chrome ([`cdp-connect`](https://www.skyvern.com/docs/developers/self-hosted/browser)).
- Its Human Interaction block is the only documented pause-approve-**resume** primitive that self-hosts.
- It beats us on secrets (1Password/Bitwarden/Azure KV + TOTP vs our SSM + post-hoc redaction) and on replay (`run_with="code"`, zero inference).
- The gap: no way to express "click every button on this form except Presentar" — encoding the never-click list means rebuilding our step layer inside theirs.
- Blockers: self-hosted Skyvern has no anti-bot layer, and AGPL-3.0 is a hazard if browser-api is ever hosted for anyone but us. Estimate 4–8 weeks, landing with weaker determinism.

## Q2 — Which components are commodity?

- **Driver layer** (1,235 LOC, 22% of src) — yes, strongly. Replace with Playwright MCP `--cdp-endpoint`, Chrome DevTools MCP `--browserUrl`, or `cdp-use`; 3–5 weeks, blast radius 1–3 files because `playwright_base.py` isolates the surface. Delete `nodriver.py` (530 LOC pinned to nodriver 0.48 internals) first.
- **MCP surface** (15 tools, 305 LOC) — yes, but see Q5: adopting Playwright MCP *is* the risk, because theirs ships `click`/`fill`/`type`.
- **Captcha/login detection** (`probe.py`, 11 selectors, 3 phrases) — yes, and ours is thin: vendor-specific strings that rot; the highest-decay, lowest-LOC piece we own.
- **DOM sanitization** (`html.py`) — partly; `ariaSnapshot`, Stagehand's AX tree and browser-use's DOMSnapshot all cover it. Low value to keep, low cost to keep.
- **Wait/poll logic** (`waits.py`, 119 LOC) — no. Nothing else offers a five-state poll that re-resolves the locator each tick and avoids script-injecting native waits.
- **YAML flow engine** (~1,543 LOC) — no. Every alternative (Skyvern blocks, workflow-use JSON, Stagehand action cache) is a recording, not reviewable source.

## Q3 — What is worth continuing to own?

- **The negative constraints.** Six mandatory handoffs sit on the critical path (SAT captcha + Enviar, Sellar, Presentar, Banamex NetKey, Aceptar, manual nav to payment). An NL agent told "pay the taxes" has every reason to click Aceptar.
- **The one-`goto`-per-session rule.** Deep-linking can lock the account; the payment form is reached by a click chain that dismisses a fraud-warning modal en route. Every NL agent's cheapest tool is `browser_navigate`.
- **The `heal` subsystem.** SAT rotates a numeric DOM-id prefix per redeployment; ours is a deterministic, auditable, one-shot rewrite, where Stagehand's `selfHeal` re-infers per call with an LLM.
- **Exact-value determinism.** Concept codes not derivable from the page; semantic similarity between two Spanish dropdown labels files a legally binding wrong return.
- **Does not survive scrutiny:** "stealth by construction" (Q4) and "self-healing hooks", which are not in `src/` — only a static `FallbackSelector` chain.

## Q4 — Detection reality check

- [FP-Agent](https://arxiv.org/abs/2605.01247) (May 2026, [code](https://github.com/ethanbwang/fp-agent), [data](https://osf.io/j6b5p/)): fingerprint features alone F₁ 0.822, **behavioral features alone 0.9994**, combined 1.000. Cloudflare's free bot management blocked 1 of 7 agents — Manus, and only because it self-identifies. [MEASUREMENT]
- [Detecting Bot Detection](https://arxiv.org/html/2606.14525v1) (Jun 2026, 40,000 visits, unmodified Playwright): 15.2% soft-block headless, 7.2% headed, 37.0% on Cloudflare zones — and 75% of the headless penalty was recovered by spoofing UA and `sec-ch-ua` alone. [MEASUREMENT]
- The one independent stealth benchmark ([Paterson, 651 verdicts](https://ianlpaterson.com/blog/anti-detect-browser-benchmark-patchright-nodriver-curl-cffi/)): nodriver 28/31, patchright and Camoufox 25/31, **vanilla Playwright 24/31** — the whole stealth stack was worth ~4 targets. [MEASUREMENT, narrow]
- Two vectors are dead: `Runtime.enable` was [closed at the source in Chrome M137](https://blog.castle.io/why-a-classic-cdp-bot-detection-signal-suddenly-stopped-working-and-nobody-noticed/), and `isTrusted` is not the discriminator (CDP `Input.*` yields `isTrusted:true`). What betrays an agent is missing telemetry plus the [coordinate leak](https://bugs.chromium.org/p/chromium/issues/detail?id=1477537) `pageX==screenX`.
- Vendors: Cloudflare's [Precursor](https://blog.cloudflare.com/introducing-precursor/) scores pointer/keyboard rhythm per session [VENDOR CLAIM]; [Akamai](https://www.akamai.com/blog/security-research/identifying-agentic-automation-behavioral-telemetry) published the only real evaluation — 63.2% of agent requests carried zero mouse events, ROC-AUC 0.981 — labelled on Comet, Atlas and the Claude Chrome extension, i.e. real browsers with real profiles. [MEASUREMENT]
- Bites us specifically: since [Chrome 136](https://developer.chrome.com/blog/remote-debugging-port) `--remote-debugging-port` is ignored on the default user-data-dir, and `patchright.py:6-9` states `connect_over_cdp` bypasses patchright's stealth patches — our production path is attach mode.

## Q5 — Keep the stealth driver, replace the flow layer with NL actions?

- No, and the flow layer is the wrong half to replace; the right hybrid is the inverse.
- **Determinism**: 204 steps replayed monthly become 204 inference round-trips against a portal whose session expires in 16 minutes.
- **Reviewability**: a YAML diff is what code review acts on; an NL prompt has no reviewable artifact.
- **Redaction**: `redact=` is scoped to a flow run, so ad-hoc `dom`/`screenshot` reads fall outside it — a hole that exists in browser-api today.
- **The never-click guarantee** is unrecoverable: no page-level signal distinguishes the verify screen from the done screen in advance.
- The defensible hybrid: adopt Playwright MCP or `cdp-use` as the transport behind `drivers/base.py`, keep steps/actions/session and the `human_needed` + VNC outcome, and adopt Browser Use's `sensitive_data` design (domain-scoped placeholders enforced at construction).

## Q6 — Risks of continuing to own it

- **Driver maintenance**: ~1,000 of 1,235 LOC is Playwright-family or raw-CDP specific. Playwright drift is contained to 1–3 files; CDP drift is not — `nodriver.py` hard-codes VK codes and CDP sequences documented as workarounds for nodriver 0.48 internals.
- **Upstream bus factor**: patchright 2 maintainers (healthiest), Camoufox 1 and still beta, nodriver 1 and silent since 2026-05-13, undetected-chromedriver dead. Two of the three layers we wrap have already stalled once.
- **Test coverage**: the architecture is enforced by test, but no test launches a real browser and there is no coverage config, so a Chromium or nodriver upgrade breaks silently.
- **Doc/code drift**: two contradictory `## Architecture` sections, sanitization levels documented but unreachable from YAML, `human_needed` absent from the README.
- **Code execution**: `parse.py` `eval`-ed a type string from a user-supplied schema file — a real finding independent of this question (see Findings).
- **Version skew**: browser-api pins `llm-browser>=0.7,<0.8` while facturacion-sat's venv carries a different patchright, and 16 banned `eval:` steps survive across 10 flow files.

## Recommended next step — one week, read-only, no payment or filing flow

1. **Day 1–2, does it connect?** Point `npx @playwright/mcp --cdp-endpoint ws://windows:9223/...` at the warmed Chrome. Two known blockers: Chrome rejects non-IP `Host` headers on `/json/version` (pass the `ws://` URL directly), and [Chrome 136](https://developer.chrome.com/blog/remote-debugging-port) ignores the port on the default user-data-dir. Failure here kills the transport swap — a cheap, decisive result.
2. **Day 3–4, fidelity and cost.** Re-implement `flows/sat/login.yaml` and `flows/banamex/select_account.yaml` as tool sequences; record wall-clock, input+output tokens, and whether the a11y snapshot surfaces Banamex's hidden native `<select>` elements. Compare against the zero-inference YAML replay baseline.
3. **Day 5, detection delta.** Run patchright attach, Playwright MCP attach and raw `cdp-use` attach against [bot-detector.rebrowser.net](https://bot-detector.rebrowser.net/), [Brotector](https://github.com/kaliiiiiiiiii/brotector), [datadome.co/bot-tester](https://datadome.co/bot-tester/) and [are_you_a_bot](https://deviceandbrowserinfo.com/are_you_a_bot); record `pwInitScripts`, `mainWorldExecution`, `Input.untrusted` and the coordinate leak. Hypothesis to falsify: attach-mode patchright already scores no better than plain Playwright.
4. **Day 5, guardrails, by inspection.** Enumerate which of the six handoffs and the never-click list Playwright MCP's tool surface can express. Expected answer: none.
5. **Decide.** If 1–4 succeed and 3 shows no stealth loss, swap the transport and keep the flow layer. If 1 fails, keep both and delete `nodriver.py` instead.

## Findings to act on

| Finding | Where | Status |
|---|---|---|
| Attach mode voids patchright's stealth patches — they are injected by `launch`/`launch_persistent_context`, not `connect_over_cdp`, so production runs with less stealth than the README implies | `drivers/patchright.py:6-9` | Open — falsify on day 5 above |
| `eval(type_str, vars(typing))` on a string from a user-supplied YAML schema: arbitrary code execution via a schema path | `parse.py`, `build_model` | **Fixed** — the type string is now parsed against an allowlist (`schema_types.py`) |
| browser-api tab tools never receive `injected`, and screenshots are raw PNG bytes no redactor touches, so `redact=` does not cover ad-hoc reads | browser-api tab tools | Open |

## Unverified

- Whether patchright's patches survive `connect_over_cdp` — our own driver docstring says they do not; no measurement either way.
- Whether Stagehand v4's `connect()` works cross-host, since it needs its extension resident on the target browser.
- Whether Browserless's humanized cadence produces trusted or synthetic input.
- Hyperbrowser's `useStealth`/`useUltraStealth` mechanism; Zapier's approve-and-resume; whether Magentic-UI resumes a live browser session.
- No published detection measurement against any banking portal has ever been found, and no substantiated case of a named bank locking a named account for browser automation.
- Our own account-lockout claim: attested by prose and by the shape of a remediation commit, but no incident report exists in the history — partially unverified.
- Whether "profile warming" helps at all; every claim traces to antidetect-browser vendors selling warming tools.
