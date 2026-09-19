# Changelog

## 0.2.0 — 2026-09-19

### Added

- `template.resolve_template` accepts dotted paths: `{{ link.href }}`,
  `{{ links.0.text }}`; an int segment indexes a list (ocampor/toolshed#61).
- `template.TemplatePathError` (a `ValueError`): a dotted path that resolves to
  nothing. A plain `{{ var }}` missing from data is still left in place.
- `template.resolve_path`, `template.template_names`.
