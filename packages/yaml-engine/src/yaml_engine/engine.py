"""Base engine: load compiled groups and apply them to records."""

from pathlib import Path
from typing import Any

import yaml

from yaml_engine.actions import execute_action
from yaml_engine.compile import compile_group, load_groups
from yaml_engine.conditions import evaluate_condition
from yaml_engine.types import CompiledGroup, CompiledRule


def get_field(record: dict[str, object], field: str) -> object:
    """Resolve a dot-notation field path from a record dict."""
    parts = field.split(".")
    value: object = record.get(parts[0])
    for part in parts[1:]:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def resolve_field(
    field: str,
    source: str,
    record: dict[str, object],
    context: dict[str, object],
) -> object:
    """Return the field value from context or record."""
    if source == "context":
        return context.get(field)
    return get_field(record, field)


def rule_matches(
    rule: CompiledRule,
    record: dict[str, object],
    context: dict[str, object],
) -> bool:
    """Return True if all conditions in the rule pass."""
    for cond in rule.conditions:
        value = resolve_field(cond.field, cond.source, record, context)
        if not evaluate_condition(cond.op, value, cond.param):
            return False
    return True


def apply_matched_rule(
    rule: CompiledRule,
    record: dict[str, object],
) -> None:
    """Execute all actions for a matched rule."""
    for action in rule.actions:
        execute_action(action.op, record, action.param)


def apply_group(
    group: CompiledGroup,
    record: dict[str, object],
    context: dict[str, object],
) -> None:
    """Evaluate a group's rules against record and apply matched actions."""
    if group.skip_if_set and record.get(group.skip_if_set):
        return

    for rule in group.rules:
        if not rule_matches(rule, record, context):
            continue
        apply_matched_rule(rule, record)
        if group.first_match:
            return


class Engine:
    """Compiled engine. Build once, call apply() many times."""

    def __init__(self, groups: list[CompiledGroup]) -> None:
        self.groups = groups  # already sorted by priority

    @classmethod
    def from_directory(cls, path: str | Path) -> "Engine":
        """Load and compile all YAML files in a directory."""
        return cls(load_groups(Path(path)))

    @classmethod
    def from_file(cls, path: str | Path) -> "Engine":
        """Load and compile a single YAML file as one group."""
        raw: dict[str, Any] = yaml.safe_load(Path(path).read_text())
        return cls([compile_group(raw)])

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "Engine":
        """Compile a single group from a raw dict."""
        return cls([compile_group(raw)])

    def apply(
        self,
        record: dict[str, object],
        context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Apply all rule groups to record in priority order. Mutates and returns record."""
        ctx = context or {}
        for group in self.groups:
            apply_group(group, record, ctx)
        return record
