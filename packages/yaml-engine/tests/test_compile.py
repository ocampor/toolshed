"""Tests for YAML compilation."""

import textwrap
from pathlib import Path

import yaml

from yaml_engine.compile import compile_condition, compile_action, compile_group, load_groups


def test_compile_condition_eq():
    cond = compile_condition({"field": "name", "op": "eq", "value": "Alice"})
    assert cond.field == "name"
    assert cond.op == "eq"
    assert cond.param == "alice"  # lowered
    assert cond.source == "record"


def test_compile_condition_with_context_source():
    cond = compile_condition({"field": "bank", "op": "eq", "value": "Klar", "source": "context"})
    assert cond.source == "context"


def test_compile_condition_in_set():
    cond = compile_condition({"field": "type", "op": "in", "values": ["A", "B", "c"]})
    assert cond.param == frozenset({"a", "b", "c"})


def test_compile_condition_matches():
    cond = compile_condition({"field": "desc", "op": "matches", "pattern": r"SPEI.*"})
    assert cond.param.pattern == r"SPEI.*"  # type: ignore[union-attr]


def test_compile_condition_unknown_op_passes():
    """Unknown ops should not raise — consumers may register custom conditions."""
    cond = compile_condition({"field": "x", "op": "custom_op", "value": "test"})
    assert cond.op == "custom_op"
    assert cond.param == "test"


def test_compile_action_generic():
    action = compile_action({"set": {"category": "Travel"}})
    assert action.op == "set"
    assert action.param == {"category": "Travel"}


def test_compile_action_unknown_raises():
    import pytest
    with pytest.raises(ValueError, match="Unknown action format"):
        compile_action({})


def test_compile_group_basic():
    raw = yaml.safe_load(textwrap.dedent("""
        group: test
        priority: 10
        options:
          first_match: true
          skip_if_set: category
        rules:
          - conditions:
              - field: desc
                op: eq
                value: hello
            actions:
              - set: {category: Greeting}
    """))
    group = compile_group(raw)
    assert group.name == "test"
    assert group.priority == 10
    assert group.first_match is True
    assert group.skip_if_set == "category"
    assert len(group.rules) == 1
    assert len(group.rules[0].conditions) == 1
    assert len(group.rules[0].actions) == 1


def test_load_groups_from_directory(tmp_path: Path):
    (tmp_path / "a.yaml").write_text(textwrap.dedent("""
        group: second
        priority: 20
        rules: []
    """))
    (tmp_path / "b.yaml").write_text(textwrap.dedent("""
        group: first
        priority: 5
        rules: []
    """))
    groups = load_groups(tmp_path)
    assert [g.name for g in groups] == ["first", "second"]
