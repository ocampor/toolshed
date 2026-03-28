"""Template variable substitution for YAML values.

Supports {{ var }} syntax in strings, resolving against a data dict.
"""

import re

_TEMPLATE_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def resolve_template(value: str, data: dict[str, object]) -> str:
    """Replace all {{ var }} placeholders in value with values from data.

    If a variable is not found in data, the placeholder is left as-is.
    If the entire value is a single {{ var }} and resolves to a non-string,
    the string representation is returned.
    """
    def replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        resolved = data.get(key)
        if resolved is None:
            return match.group(0)  # leave placeholder as-is
        return str(resolved)

    return _TEMPLATE_RE.sub(replacer, value)


def resolve_templates_in_dict(raw: dict[str, object], data: dict[str, object]) -> dict[str, object]:
    """Recursively resolve {{ var }} placeholders in all string values of a dict."""
    result: dict[str, object] = {}
    for key, value in raw.items():
        if isinstance(value, str):
            result[key] = resolve_template(value, data)
        elif isinstance(value, dict):
            result[key] = resolve_templates_in_dict(value, data)  # type: ignore[arg-type]
        elif isinstance(value, list):
            result[key] = [
                resolve_templates_in_dict(item, data) if isinstance(item, dict)
                else resolve_template(item, data) if isinstance(item, str)
                else item
                for item in value
            ]
        else:
            result[key] = value
    return result
