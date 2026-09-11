"""Resolve a YAML schema ``type:`` string to a real Python type.

The string comes from a user-supplied schema file, so it is parsed to an AST
and walked against ``constants.SCHEMA_TYPE_NAMES`` — never evaluated. The
grammar is the allowlisted names plus ``X | Y``, ``Optional[X]``, ``list[X]``
and ``dict[str, X]``; anything else raises ``ValueError``.
"""

import ast
from typing import Any

from llm_browser import constants


def resolve_type(type_str: str) -> Any:
    try:
        expression = ast.parse(type_str, mode="eval")
    except SyntaxError as error:
        raise ValueError(f"unsupported schema type: {type_str!r}") from error
    return resolve_node(expression.body)


def unsupported(node: ast.AST) -> ValueError:
    return ValueError(f"unsupported schema type: {ast.unparse(node)!r}")


def resolve_node(node: ast.expr) -> Any:
    if isinstance(node, ast.Name):
        return resolve_name(node)
    if isinstance(node, ast.Constant) and node.value is None:
        return type(None)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return resolve_node(node.left) | resolve_node(node.right)
    if isinstance(node, ast.Subscript):
        return resolve_subscript(node)
    raise unsupported(node)


def resolve_name(node: ast.Name) -> Any:
    if node.id not in constants.SCHEMA_TYPE_NAMES:
        raise unsupported(node)
    return constants.SCHEMA_TYPE_NAMES[node.id]


def resolve_subscript(node: ast.Subscript) -> Any:
    container = node.value
    if not isinstance(container, ast.Name) or container.id not in SUBSCRIPT_RESOLVERS:
        raise unsupported(node)
    return SUBSCRIPT_RESOLVERS[container.id](node.slice)


def resolve_optional(item: ast.expr) -> Any:
    return resolve_node(item) | None


def resolve_list(item: ast.expr) -> Any:
    element: Any = resolve_node(item)
    return list[element]


def resolve_dict(item: ast.expr) -> Any:
    if not isinstance(item, ast.Tuple) or len(item.elts) != 2:
        raise unsupported(item)
    key, value = item.elts
    if resolve_node(key) is not str:
        raise unsupported(key)
    element: Any = resolve_node(value)
    return dict[str, element]


SUBSCRIPT_RESOLVERS = {
    "Optional": resolve_optional,
    "list": resolve_list,
    "dict": resolve_dict,
}
