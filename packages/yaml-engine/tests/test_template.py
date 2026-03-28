"""Tests for template variable substitution."""

import pytest

from yaml_engine.template import resolve_template, resolve_templates_in_dict


# --- resolve_template ---

@pytest.mark.parametrize("template, data, expected", [
    ("{{ name }}", {"name": "Alice"}, "Alice"),
    ("{{name}}", {"name": "Alice"}, "Alice"),
    ("Hello {{ name }}!", {"name": "world"}, "Hello world!"),
    ("{{ a }} and {{ b }}", {"a": "1", "b": "2"}, "1 and 2"),
    ("{{ missing }}", {}, "{{ missing }}"),
    ("no vars here", {"name": "Alice"}, "no vars here"),
    ("{{ count }}", {"count": 42}, "42"),
    ("{{ rate }}", {"rate": 20.1234}, "20.1234"),
])
def test_resolve_template(template, data, expected):
    assert resolve_template(template, data) == expected


def test_resolve_template_none_value_leaves_placeholder():
    assert resolve_template("{{ x }}", {"x": None}) == "{{ x }}"


# --- resolve_templates_in_dict ---

def test_resolve_dict_simple():
    raw = {"greeting": "Hello {{ name }}", "count": 5}
    result = resolve_templates_in_dict(raw, {"name": "world"})
    assert result == {"greeting": "Hello world", "count": 5}


def test_resolve_dict_nested():
    raw = {
        "outer": {
            "inner": "{{ val }}",
        }
    }
    result = resolve_templates_in_dict(raw, {"val": "resolved"})
    assert result == {"outer": {"inner": "resolved"}}


def test_resolve_dict_list():
    raw = {
        "items": [
            {"name": "{{ a }}"},
            {"name": "{{ b }}"},
            "plain {{ c }}",
            42,
        ]
    }
    result = resolve_templates_in_dict(raw, {"a": "X", "b": "Y", "c": "Z"})
    assert result == {
        "items": [
            {"name": "X"},
            {"name": "Y"},
            "plain Z",
            42,
        ]
    }


def test_resolve_dict_missing_vars_preserved():
    raw = {"field": "{{ known }} and {{ unknown }}"}
    result = resolve_templates_in_dict(raw, {"known": "yes"})
    assert result == {"field": "yes and {{ unknown }}"}
