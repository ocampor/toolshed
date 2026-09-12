# Flow Language Reference

The flow-language reference now lives in the **`browser-flows` skill** as the
single maintained source, alongside the `claude_ai_Browser` MCP server notes
that use this same language:

- `claude/skills/browser-flows/reference.md` — the full flow language (this
  content), and
- `claude/skills/browser-flows/SKILL.md` — authoring workflow and MCP deltas,

in the [`ocampor/env-sync`](https://github.com/ocampor/env-sync) repo. It
deploys to `~/.claude/skills/browser-flows/` via `env-sync`.

When the flow language changes in this package's code (`src/llm_browser/`),
update `reference.md` in that skill.
