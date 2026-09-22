"""Turning a pydantic model into the markdown table that documents it.

Split from :mod:`llm_browser.docgen`, which decides *which* models each
document is made of; this decides how one of them reads.
"""

import inspect
import re
import types
import typing
from enum import Enum

from pydantic import BaseModel
from pydantic.fields import FieldInfo

# A default longer than this says nothing a reader can use in a table cell.
DEFAULT_MAX_CHARS = 40


def render_type(annotation: object) -> str:
    """A field's type as a flow author would say it, not as pydantic holds it."""
    if annotation is None or annotation is type(None):
        return "None"
    if isinstance(annotation, typing.TypeAliasType):
        return annotation.__name__
    metadata_of = getattr(annotation, "__metadata__", None)
    if metadata_of is not None:
        return render_type(typing.get_args(annotation)[0])
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return " | ".join(f'"{arg}"' for arg in typing.get_args(annotation))
    if origin in (types.UnionType, typing.Union):
        return " | ".join(unique(render_type(a) for a in typing.get_args(annotation)))
    if origin is not None:
        args = ", ".join(render_type(a) for a in typing.get_args(annotation))
        name = getattr(origin, "__name__", str(origin))
        return f"{name}[{args}]" if args else name
    return getattr(annotation, "__name__", str(annotation))


def unique(values: typing.Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def render_value(value: object) -> str:
    if isinstance(value, Enum):
        return repr(value.value)
    if isinstance(value, BaseModel):
        return repr(value)
    return repr(value)


def render_default(field: FieldInfo) -> str:
    if field.is_required():
        return "required"
    value = field.default_factory() if field.default_factory else field.default  # type: ignore[call-arg]
    text = render_value(value)
    return text if len(text) <= DEFAULT_MAX_CHARS else "—"


def field_rows(model: type[BaseModel], names: typing.Iterable[str]) -> list[list[str]]:
    rows = []
    for name in names:
        field = model.model_fields[name]
        alias = field.alias or name
        rows.append(
            [
                f"`{alias}`",
                f"`{render_type(field.annotation)}`",
                f"`{render_default(field)}`",
                field.description or "",
            ]
        )
    return rows


def table(headings: list[str], rows: list[list[str]]) -> str:
    """A pipe inside a cell would end it, so every cell is escaped once here."""
    divider = " | ".join("---" for _ in headings)
    body = "".join(
        f"| {' | '.join(cell.replace('|', chr(92) + '|') for cell in row)} |\n"
        for row in rows
    )
    return f"| {' | '.join(headings)} |\n| {divider} |\n{body}"


def field_table(model: type[BaseModel], names: typing.Iterable[str]) -> str:
    rows = field_rows(model, names)
    if not any(row[-1] for row in rows):
        rows = [row[:-1] for row in rows]
        return table(["field", "type", "default"], rows)
    return table(["field", "type", "default", "meaning"], rows)


# Docstrings are written in reST for the editor; the docs are markdown.
RST_ROLE = re.compile(r":(?:class|func|meth|attr|mod|data|exc):`~?([^`]+)`")


def docstring(obj: object) -> str:
    text = inspect.getdoc(obj) or ""
    text = RST_ROLE.sub(lambda m: f"`{m.group(1).rsplit('.', 1)[-1]}`", text)
    return text.replace("``", "`")


def model_section(
    title: str, model: type[BaseModel], names: list[str] | None = None
) -> str:
    fields = model.model_fields if names is None else names
    parts = [f"## {title}", docstring(model)]
    if fields:
        parts.append(field_table(model, fields))
    return "\n\n".join(part for part in parts if part) + "\n"


def render_signature(name: str, member: object) -> str:
    """``name(params) -> return``, without the quotes a postponed annotation
    leaves on every type."""
    try:
        signature = inspect.signature(member)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return name
    parts = []
    for parameter in signature.parameters.values():
        if parameter.name == "self":
            continue
        if parameter.kind is parameter.KEYWORD_ONLY and "*" not in parts:
            parts.append("*")
        parts.append(render_parameter(parameter))
    returns = signature.return_annotation
    suffix = "" if returns is signature.empty else f" -> {annotation_text(returns)}"
    return f"{name}({', '.join(parts)}){suffix}"


def render_parameter(parameter: inspect.Parameter) -> str:
    text = parameter.name
    if parameter.annotation is not parameter.empty:
        text += f": {annotation_text(parameter.annotation)}"
    if parameter.default is not parameter.empty:
        text += f" = {render_value(parameter.default)}"
    return text


def annotation_text(annotation: object) -> str:
    return annotation if isinstance(annotation, str) else render_type(annotation)
