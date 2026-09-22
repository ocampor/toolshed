"""Driver registry and resolver, and which backend to pick.

Drivers plug in via object injection (BrowserSession(driver=MyDriver()))
or by name through the registry (BrowserSession(driver="patchright")).

What a driver is for
--------------------
``Behavior`` humanizes *timing* only — inter-key gaps, click jitter, mouse
paths, pauses. Runtime JS fingerprints (navigator, WebGL, canvas, CDP
detection) are the driver's job: ``patchright`` removes Playwright's
automation fingerprints on a freshly launched Chromium, ``camoufox`` spoofs
fingerprints at the C++ level. Against the hardest targets (Cloudflare JSD on
a busy site, Akamai Bot Manager) a launched automation context loses whatever
is applied to it; the supported path is attach mode — launch Chromium
yourself with a warmed profile and connect over CDP. Generic bot-test pages
do not predict a specific vendor's verdict; probe the real target.

Backend gaps that fail quietly
------------------------------
Pick the driver before the selector. On ``nodriver``: an XPath selector is
handed to a CSS query and never matches, a ``press`` chord (``Control+a``)
types its own text into the field and reports success, and ``download`` raises
``NotImplementedError``. A ``FallbackSelector`` works there only if both
branches are CSS. Reach a label-anchored control with ``:has()`` and attribute
selectors instead.

Headless
--------
The Chromium-based drivers leak ``HeadlessChrome`` in the User-Agent and fall
back to SwiftShader for WebGL when headless, both cheap detection signals; run
them headed or under Xvfb. ``camoufox`` spoofs both even headless and is the
only viable headless option against strict detectors. ``scripts/stealth_probe.py``
reproduces the measurement.
"""

from functools import lru_cache

from yaml_engine.registry import Registry

from llm_browser.drivers.base import Driver
from llm_browser.drivers.handle import DriverHandle, DriverNotInstalledError
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
