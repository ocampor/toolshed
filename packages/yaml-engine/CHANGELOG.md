# Changelog

## 0.2.0 — 2026-09-19

### Breaking

- `template.resolve_template` resolves dotted paths (`{{ link.href }}`,
  `{{ links.0.text }}`; an int segment indexes a list) instead of leaving them
  literal, and raises `template.TemplatePathError` (a `ValueError`) when the
  path reaches nothing (ocampor/toolshed#61). A plain `{{ var }}` missing from
  data is still left in place.

Migration:

- A string that must keep a literal `{{ a.b }}` needs a dotless placeholder
  name, or `a.b` present in the data. `llm-browser` is the only in-repo
  consumer of `yaml_engine.template`.
- Callers that treated an unresolvable placeholder as a no-op must catch
  `template.TemplatePathError`.

### Added

- `template.resolve_path`, `template.template_names`.
