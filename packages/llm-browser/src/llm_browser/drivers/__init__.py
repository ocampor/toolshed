"""Driver registry and resolver.

Drivers plug in via object injection (BrowserSession(driver=MyDriver()))
or by name through the registry (BrowserSession(driver="patchright")).
"""

from functools import lru_cache

from yaml_engine.registry import Registry

from llm_browser.drivers.base import Driver, DriverHandle, DriverNotInstalledError
from llm_browser.drivers.patchright import PatchrightDriver

DEFAULT_DRIVER_NAME = "patchright"


@lru_cache(maxsize=1)
def get_registry() -> Registry[type[Driver]]:
    registry = Registry[type[Driver]]("driver")
    registry.register(PatchrightDriver.name, PatchrightDriver)
    _register_optional_drivers(registry)
    return registry


def _register_optional_drivers(registry: Registry[type[Driver]]) -> None:
    """Self-register optional drivers whose extras are installed.

    Missing extras are silently skipped — string lookup then raises
    DriverNotInstalledError only when the driver is actually requested.
    """
    try:
        from llm_browser.drivers.camoufox import CamoufoxDriver  # type: ignore[import-untyped,unused-ignore]

        registry.register(CamoufoxDriver.name, CamoufoxDriver)
    except ImportError:
        pass
    try:
        from llm_browser.drivers.nodriver import NodriverDriver  # type: ignore[import-untyped,unused-ignore]

        registry.register(NodriverDriver.name, NodriverDriver)
    except ImportError:
        pass


def resolve_driver(driver: Driver | str | None) -> Driver:
    """Return a Driver instance.

    - `None` → default driver (patchright)
    - `str`  → registry lookup, default-constructed instance
    - `Driver` instance → passthrough (no mutation, no registration needed)
    """
    if isinstance(driver, Driver):
        return driver
    name = driver if isinstance(driver, str) else DEFAULT_DRIVER_NAME
    registry = get_registry()
    if name not in registry:
        raise DriverNotInstalledError(
            f"Unknown driver {name!r}. Install its extra with "
            f"`pip install llm-browser[{name}]` or pass a Driver instance."
        )
    return registry.get(name)()


__all__ = [
    "DEFAULT_DRIVER_NAME",
    "Driver",
    "DriverHandle",
    "DriverNotInstalledError",
    "PatchrightDriver",
    "get_registry",
    "resolve_driver",
]
