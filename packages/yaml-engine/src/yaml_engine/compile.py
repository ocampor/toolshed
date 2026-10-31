import re
from pathlib import Path
from typing import Any, NamedTuple

import yaml

from yaml_engine.types import (
    CompiledAction,
    CompiledCondition,
    CompiledGroup,
    CompiledParam,
    CompiledRule,
)


def compile_condition(raw: dict[str, object]) -> CompiledCondition[CompiledParam]:
    field = str(raw["field"])
    op = str(raw["op"])
    source = str(raw.get("source", "record"))
    param: CompiledParam = None

    match op:
        case "matches":
            param = re.compile(str(raw["pattern"]), re.IGNORECASE)
        case "in" | "in_set":
            values = raw.get("values", [])
            assert isinstance(values, list)
            param = frozenset(str(v).lower() for v in values)
        case "all_present" | "has_fragment":
            values = raw.get("values", [])
            assert isinstance(values, list)
            param = [str(v).upper() for v in values]
        case "eq" | "neq":
            param = str(raw["value"]).lower()
        case "contains":
            param = str(raw["value"])
        case "gt" | "lt":
            param = raw["value"]  # type: ignore[assignment]
        case "is_null" | "not_null" | "is_truthy":
            param = None
        case _:
            # Allow unknown ops — consumers may register custom conditions
            param = raw.get("value", raw.get("values"))  # type: ignore[assignment]

    return CompiledCondition(field=field, op=op, param=param, source=source)  # type: ignore[arg-type]


def compile_action(raw: dict[str, object]) -> CompiledAction[CompiledParam]:
    """The first recognized key is the action op."""
    for key, value in raw.items():
        return CompiledAction(op=key, param=value)  # type: ignore[arg-type]
    raise ValueError(f"Unknown action format: {raw!r}")


class GroupOptions(NamedTuple):
    name: str
    priority: int
    first_match: bool
    skip_if_set: str | None


def compile_options(raw: dict[str, object]) -> GroupOptions:
    raw_priority = raw.get("priority", 0)
    priority = int(raw_priority) if isinstance(raw_priority, (int, float, str)) else 0
    options: dict[str, object] = raw.get("options", {})  # type: ignore[assignment]
    return GroupOptions(
        name=str(raw.get("group", "")),
        priority=priority,
        first_match=bool(options.get("first_match", True)),
        skip_if_set=str(options["skip_if_set"]) if "skip_if_set" in options else None,
    )


def as_list(value: object) -> list[dict[str, object]]:
    if isinstance(value, list):
        return value
    return []


def compile_rules(raw_rules: list[dict[str, object]]) -> tuple[CompiledRule, ...]:
    return tuple(
        CompiledRule(
            conditions=tuple(compile_condition(c) for c in as_list(raw_rule.get("conditions"))),
            actions=tuple(compile_action(a) for a in as_list(raw_rule.get("actions"))),
        )
        for raw_rule in raw_rules
    )


def compile_group(raw: dict[str, object]) -> CompiledGroup:
    options = compile_options(raw)
    raw_rules: list[dict[str, object]] = raw.get("rules", [])  # type: ignore[assignment]
    return CompiledGroup(
        name=options.name,
        priority=options.priority,
        first_match=options.first_match,
        skip_if_set=options.skip_if_set,
        rules=compile_rules(raw_rules),
    )


def load_groups(rules_dir: Path) -> list[CompiledGroup]:
    groups: list[CompiledGroup] = []
    for path in sorted(rules_dir.glob("*.yaml")):
        raw: dict[str, Any] = yaml.safe_load(path.read_text())
        groups.append(compile_group(raw))
    return sorted(groups, key=lambda g: g.priority)
