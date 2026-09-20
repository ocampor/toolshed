# Changelog

## 0.2.0 — 2026-09-19

### Breaking

- `template.resolve_template` resolves dotted paths (`{{ a.b }}`, `{{ list.0.b }}`) and raises `template.TemplatePathError` (a `ValueError`) when one reaches nothing; a missing plain `{{ var }}` is still left in place (ocampor/toolshed#61).

Migration:

- A literal `{{ a.b }}` needs a dotless placeholder name, or `a.b` present in the data.
- Callers that treated an unresolvable placeholder as a no-op must catch `template.TemplatePathError`.

### Added

- `template.resolve_path`, `template.template_names`.
