# Turning a real failure into a fixture

The suite is meant to grow out of production failures. The recipe:

1. **Capture the page.** From a live session:
   `llm-browser dom --selector body --level low` plus a screenshot; from a
   failed flow, the `dom` and `screenshot` paths already on the `FlowError`.
2. **Strip it to the minimum that still reproduces.** Keep the element(s),
   the CSS that governs their visibility and layout, and the JS that mutates
   them. Replace every external script with a few inline lines that mimic the
   timing (`setTimeout`, driven by `?delay=`). No external requests, no
   secrets, no real content, no analytics — the page must be self-contained
   and under ~100 lines.
3. **Paste in the isTrusted recorder** (the snippet above), so the new page
   can answer trust questions like every other one.
4. **Name it after the failure mode**, not the site:
   `overlay-intercepts-click.html`. Add a flow under
   `src/llm_browser_conformance/flows/` reproducing the original steps, and a
   scenario asserting the behaviour you *want* — the fix's behaviour. Until
   the library is fixed, list it in `known_gaps` (`xfail(strict=True)` under
   pytest) so the suite documents the gap instead of hiding it.
5. **Run it:** `uv run llm-browser-check --driver <the one that failed>`.
6. **Cite the origin** in a one-line HTML comment at the top of the page —
   site and date only, no URL parameters, no identifying data.

