"""Integration tests for the base Engine."""

import textwrap
from pathlib import Path

import yaml

from yaml_engine.actions import register_action
from yaml_engine.engine import Engine


# --- Register test actions (yaml-engine ships no built-in actions) ---

@register_action("set")
def set_fields(record: dict[str, object], param: dict[str, object]) -> None:
    record.update(param)


@register_action("negate")
def negate(record: dict[str, object], param: str) -> None:
    value = record.get(param)
    if value is not None:
        record[param] = -value  # type: ignore[operator]


# --- Tests ---

def test_basic_eq_rule():
    engine = Engine.from_dict(yaml.safe_load(textwrap.dedent("""
        group: test
        priority: 0
        rules:
          - conditions:
              - field: type
                op: eq
                value: interest
            actions:
              - set: {is_savings: true}
    """)))
    result = engine.apply({"type": "interest"})
    assert result["is_savings"] is True


def test_no_match_leaves_record_unchanged():
    engine = Engine.from_dict(yaml.safe_load(textwrap.dedent("""
        group: test
        priority: 0
        rules:
          - conditions:
              - field: type
                op: eq
                value: interest
            actions:
              - set: {is_savings: true}
    """)))
    result = engine.apply({"type": "charge"})
    assert result.get("is_savings") is None


def test_skip_if_set():
    engine = Engine.from_dict(yaml.safe_load(textwrap.dedent("""
        group: test
        priority: 0
        options:
          skip_if_set: category
        rules:
          - conditions:
              - field: desc
                op: contains
                value: WALMART
            actions:
              - set: {category: Shopping}
    """)))
    record = {"desc": "WALMART", "category": "Already Set"}
    result = engine.apply(record)
    assert result["category"] == "Already Set"


def test_first_match_stops_after_first_rule():
    engine = Engine.from_dict(yaml.safe_load(textwrap.dedent("""
        group: test
        priority: 0
        options:
          first_match: true
        rules:
          - conditions:
              - field: desc
                op: contains
                value: WALMART
            actions:
              - set: {category: Shopping}
          - conditions:
              - field: desc
                op: contains
                value: WALMART
            actions:
              - set: {category: Overwritten}
    """)))
    result = engine.apply({"desc": "WALMART STORE"})
    assert result["category"] == "Shopping"


def test_first_match_false_applies_all():
    engine = Engine.from_dict(yaml.safe_load(textwrap.dedent("""
        group: test
        priority: 0
        options:
          first_match: false
        rules:
          - conditions:
              - field: type
                op: in
                values: [charge, withdrawal]
              - field: amount
                op: gt
                value: 0
            actions:
              - negate: amount
          - conditions:
              - field: type
                op: eq
                value: charge
            actions:
              - set: {is_expense: true}
    """)))
    result = engine.apply({"type": "charge", "amount": 100.0})
    assert result["amount"] == -100.0
    assert result["is_expense"] is True


def test_context_condition():
    engine = Engine.from_dict(yaml.safe_load(textwrap.dedent("""
        group: test
        priority: 0
        rules:
          - conditions:
              - field: bank
                source: context
                op: eq
                value: Klar
            actions:
              - set: {is_internal: true}
    """)))
    result = engine.apply({"desc": "transfer"}, context={"bank": "Klar"})
    assert result["is_internal"] is True


def test_context_condition_no_match():
    engine = Engine.from_dict(yaml.safe_load(textwrap.dedent("""
        group: test
        priority: 0
        rules:
          - conditions:
              - field: bank
                source: context
                op: eq
                value: Klar
            actions:
              - set: {is_internal: true}
    """)))
    result = engine.apply({"desc": "transfer"}, context={"bank": "Nu"})
    assert result.get("is_internal") is None


def test_dot_notation_field_access():
    engine = Engine.from_dict(yaml.safe_load(textwrap.dedent("""
        group: test
        priority: 0
        rules:
          - conditions:
              - field: details.clabe
                op: in_set
                values: ["638180000122390485"]
            actions:
              - set: {is_internal: true}
    """)))
    record = {"details": {"clabe": "638180000122390485"}}
    result = engine.apply(record)
    assert result["is_internal"] is True


def test_dot_notation_missing_nested():
    engine = Engine.from_dict(yaml.safe_load(textwrap.dedent("""
        group: test
        priority: 0
        rules:
          - conditions:
              - field: details.clabe
                op: in_set
                values: ["123"]
            actions:
              - set: {found: true}
    """)))
    result = engine.apply({"desc": "no details"})
    assert result.get("found") is None


def test_multi_group_priority_ordering(tmp_path: Path):
    def write(name: str, content: str) -> None:
        (tmp_path / name).write_text(textwrap.dedent(content))

    write("a.yaml", """
        group: high_priority
        priority: 30
        rules: []
    """)
    write("b.yaml", """
        group: low_priority
        priority: 10
        rules: []
    """)
    engine = Engine.from_directory(tmp_path)
    assert [g.name for g in engine.groups] == ["low_priority", "high_priority"]


def test_from_file(tmp_path: Path):
    (tmp_path / "rules.yaml").write_text(textwrap.dedent("""
        group: test
        priority: 0
        rules:
          - conditions:
              - field: type
                op: eq
                value: interest
            actions:
              - set: {is_savings: true}
    """))
    engine = Engine.from_file(tmp_path / "rules.yaml")
    result = engine.apply({"type": "interest"})
    assert result["is_savings"] is True
