"""Tests for the generic Registry."""

import pytest

from yaml_engine.registry import Registry


def test_register_and_get():
    reg: Registry = Registry("test")

    @reg.register("greet")
    def greet(name: str) -> str:
        return f"hello {name}"

    assert reg.get("greet")("world") == "hello world"


def test_contains():
    reg: Registry = Registry("test")

    @reg.register("foo")
    def foo() -> None:
        pass

    assert "foo" in reg
    assert "bar" not in reg


def test_get_unknown_raises():
    reg: Registry = Registry("widget")
    with pytest.raises(ValueError, match="Unknown widget: 'missing'"):
        reg.get("missing")
