# Migrating older flows

What `llm-browser validate` does with each retired spelling — the middle column is the dangerous
one, because a clean exit 0 is not a clean flow.

| Old | What happens today | Replacement |
|---|---|---|
| `action: wait` (`quiet_ms`, `timeout_s`) | rejected at load | `action: wait_for`, `state: stable`, `settle:` and `timeout:` in ms |
| `action: read_values` | rejected at load | `read` with `extract: { name: { attribute: value } }` |
| `action: dismiss_modal` | rejected at load | `click` with `when: [{ element_exists: … }]` and `optional: true` |
| `action: click_visible` | rejected at load | `wait_for` `state: visible`, then `click` |
| `action: click_all` | rejected at load | one `click` per target, or a `run-flow` child per item |
| `action: modify_dom` | rejected at load | the matching action; if none exists, request it upstream |
| `action: wait_for_load_state` | rejected at load | `goto`'s `wait_until:` |
| `wait_after: <ms>` | **accepted and executed** — `steps.py` sleeps for it | a `wait_for` step naming what the click produced |
| `fields:` block | **accepted and ignored** — a real `BaseStep` field that nothing reads | one step per field |
| `checkpoint: true` | **accepted and ignored** — not a field at all; pydantic drops it | end the flow before the human's step and re-invoke afterwards |
| `eval:` | accepted and executed | the patterns in `guide/patterns`; a page that still needs JS is a library gap |
