"""Tests for template variable substitution."""

import pytest

from yaml_engine.template import (
    TemplatePathError,
    resolve_template,
    resolve_templates_in_dict,
    template_names,
)

# --- resolve_template ---


@pytest.mark.parametrize(
    "template, data, expected",
    [
        ("{{ name }}", {"name": "Alice"}, "Alice"),
        ("{{name}}", {"name": "Alice"}, "Alice"),
        ("Hello {{ name }}!", {"name": "world"}, "Hello world!"),
        ("{{ a }} and {{ b }}", {"a": "1", "b": "2"}, "1 and 2"),
        ("{{ missing }}", {}, "{{ missing }}"),
        ("no vars here", {"name": "Alice"}, "no vars here"),
        ("{{ count }}", {"count": 42}, "42"),
        ("{{ rate }}", {"rate": 20.1234}, "20.1234"),
    ],
)
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


# --- dotted paths ---

ROWS = {"link": {"href": "/a", "n": 3}, "links": [{"text": "one"}, {"text": "two"}]}


@pytest.mark.parametrize(
    "template, expected",
    [
        ("{{ link.href }}", "/a"),
        ("{{ link.n }}", "3"),
        ("{{ links.1.text }}", "two"),
        ("x{{link.href}}/{{ links.0.text }}", "x/a/one"),
    ],
)
def test_resolve_template_dotted_path(template, expected):
    assert resolve_template(template, ROWS) == expected


@pytest.mark.parametrize(
    "template",
    [
        "{{ link.missing }}",
        "{{ links.2.text }}",
        "{{ links.first.text }}",
        "{{ link.href.deeper }}",
        "{{ nothing.href }}",
    ],
)
def test_resolve_template_dotted_path_to_nothing_raises(template):
    with pytest.raises(TemplatePathError, match="resolves to nothing"):
        resolve_template(template, ROWS)


def test_resolve_template_dotted_path_to_none_raises():
    with pytest.raises(TemplatePathError):
        resolve_template("{{ link.href }}", {"link": {"href": None}})


def test_resolve_templates_in_dict_dotted_path():
    raw = {"url": "https://x{{ link.href }}", "nested": ["{{ links.0.text }}"]}
    assert resolve_templates_in_dict(raw, ROWS) == {
        "url": "https://x/a",
        "nested": ["one"],
    }


def test_template_names_are_path_roots():
    raw = {"a": "{{ x }} {{ link.href }}", "b": [{"c": "{{ links.0.text }}"}, 3]}
    assert template_names(raw) == {"x", "link", "links"}
