"""Template variable substitution for YAML values.

Supports {{ var }} and dotted {{ var.key.0 }} syntax in strings, resolving
against a data dict.
"""

import re
from collections.abc import Iterator

_TEMPLATE_RE = re.compile(r"\{\{\s*(\w+(?:\.\w+)*)\s*\}\}")


class TemplatePathError(ValueError):
    """A dotted path named something the data does not hold."""


def resolve_path(path: str, data: dict[str, object]) -> object:
    """The value a dotted path reaches: keys index mappings, ints index lists."""
    value: object = data
    for segment in path.split("."):
        try:
            value = path_member(value, segment)
        except (KeyError, IndexError, ValueError, TypeError):
            raise TemplatePathError(f"template path {path!r} resolves to nothing at {segment!r}") from None
    if value is None:
        raise TemplatePathError(f"template path {path!r} resolves to nothing")
    return value


def path_member(value: object, segment: str) -> object:
    if isinstance(value, dict):
        return value[segment]
    if isinstance(value, list):
        return value[int(segment)]
    raise TypeError(type(value).__name__)


def resolve_template(value: str, data: dict[str, object]) -> str:
    """Replace every placeholder in value with its value from data.

    A plain {{ var }} missing from data is left as-is; a dotted path that
    resolves to nothing raises :class:`TemplatePathError`.
    """

    def replacer(match: re.Match[str]) -> str:
        path = match.group(1)
        if "." in path:
            return str(resolve_path(path, data))
        resolved = data.get(path)
        if resolved is None:
            return match.group(0)  # leave placeholder as-is
        return str(resolved)

    return _TEMPLATE_RE.sub(replacer, value)


def template_names(raw: object) -> set[str]:
    """The data names every placeholder under ``raw`` starts from."""
    return {path.split(".", 1)[0] for path in template_paths(raw)}


def template_paths(raw: object) -> Iterator[str]:
    if isinstance(raw, str):
        yield from _TEMPLATE_RE.findall(raw)
    elif isinstance(raw, dict):
        for value in raw.values():
            yield from template_paths(value)
    elif isinstance(raw, list):
        for item in raw:
            yield from template_paths(item)


def resolve_templates_in_dict(raw: dict[str, object], data: dict[str, object]) -> dict[str, object]:
    """Recursively resolve {{ var }} placeholders in all string values of a dict."""
    result: dict[str, object] = {}
    for key, value in raw.items():
        if isinstance(value, str):
            result[key] = resolve_template(value, data)
        elif isinstance(value, dict):
            result[key] = resolve_templates_in_dict(value, data)
        elif isinstance(value, list):
            result[key] = [
                resolve_templates_in_dict(item, data)
                if isinstance(item, dict)
                else resolve_template(item, data)
                if isinstance(item, str)
                else item
                for item in value
            ]
        else:
            result[key] = value
    return result
