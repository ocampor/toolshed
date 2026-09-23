# llm-browser docs

The docs ship inside the wheel. `guide/patterns.md` is hand-written and lives at
[`src/llm_browser/docs/guide/`](../src/llm_browser/docs/guide/); the `reference/`
half is rendered from the source at build time by `llm-browser docs --write`, so
it is git-ignored here and present only in a built package. Read either from
Python with `llm_browser.docs`. `RESEARCH.md` beside this file is history, not
documentation.
