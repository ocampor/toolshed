"""Tests for the driver registry and resolve_driver."""

import pytest

from llm_browser.drivers import (
    DEFAULT_DRIVER_NAME,
    Driver,
    DriverNotInstalledError,
    PatchrightDriver,
    get_registry,
    resolve_driver,
)


def test_default_driver_is_patchright() -> None:
    assert DEFAULT_DRIVER_NAME == "patchright"


def test_registry_has_patchright() -> None:
    assert "patchright" in get_registry()


def test_resolve_none_returns_default() -> None:
    assert isinstance(resolve_driver(None), PatchrightDriver)


def test_resolve_string_returns_instance() -> None:
    assert isinstance(resolve_driver("patchright"), PatchrightDriver)


def test_resolve_instance_passthrough() -> None:
    instance = PatchrightDriver()
    assert resolve_driver(instance) is instance


def test_resolve_unknown_raises() -> None:
    with pytest.raises(DriverNotInstalledError, match="Unknown driver"):
        resolve_driver("does-not-exist")


def test_subclass_injection_is_not_registered() -> None:
    class CustomDriver(PatchrightDriver):
        name = "custom-test"

    instance = CustomDriver()
    assert resolve_driver(instance) is instance
    assert "custom-test" not in get_registry()


def test_driver_is_abstract() -> None:
    assert Driver.__abstractmethods__
