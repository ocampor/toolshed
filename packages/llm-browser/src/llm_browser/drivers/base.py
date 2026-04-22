"""Driver abstract base class, handle model, and errors.

A Driver owns both lifecycle (launch/connect/close) and interactions
(click/fill/type/navigate/read). Splitting these onto one class keeps
plug-and-play simple: subclass Driver, implement every abstract method.
"""

import importlib
import time
from abc import ABC, abstractmethod
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, ClassVar

from pydantic import BaseModel

from llm_browser.behavior import Behavior, BehaviorRuntime


class DriverHandle(BaseModel):
    """Per-driver connection/lifecycle state persisted to disk."""

    driver: str
    pid: int | None = None
    endpoint: str | None = None
    user_data_dir: str
    extra: dict[str, str] = {}


class DriverNotInstalledError(RuntimeError):
    """Raised when a driver's optional extra is missing."""


def load_optional_module(module: str, extra: str) -> ModuleType:
    """Import an optional driver dependency or raise DriverNotInstalledError."""
    try:
        return importlib.import_module(module)
    except ImportError as e:
        raise DriverNotInstalledError(
            f"{extra} is not installed. Run: pip install llm-browser[{extra}]"
        ) from e


class Driver(ABC):
    """Base class for browser drivers. Owns lifecycle + interactions."""

    name: ClassVar[str]
    supports_reconnect: ClassVar[bool] = False

    # --- Lifecycle ---

    @abstractmethod
    def launch(
        self,
        user_data_dir: Path,
        url: str | None,
        headed: bool,
        executable_path: str | None = None,
    ) -> DriverHandle: ...

    def attach(self, cdp_url: str) -> DriverHandle:
        """Attach to an already-running Chromium over CDP.

        Subclasses that support it (patchright) override this. Others raise.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support attach; use driver='patchright'"
        )

    @abstractmethod
    def page(self, handle: DriverHandle) -> Any: ...

    @abstractmethod
    def close(self, handle: DriverHandle) -> None: ...

    @abstractmethod
    def status(self, handle: DriverHandle) -> bool: ...

    def can_resume_across_processes(self, handle: DriverHandle) -> bool:
        """Whether the browser survives the current Python process exiting.

        Used by ``FlowRunner`` to refuse checkpoint-based flows on sessions
        that can't be resumed. Default False — override when a driver+handle
        combination can be reconnected from persisted state (e.g. patchright
        in attach mode via ``connect_over_cdp``).
        """
        return False

    @abstractmethod
    def latest_tab(self, handle: DriverHandle) -> Any: ...

    # --- Selector resolution ---

    @abstractmethod
    def resolve(self, page: Any, selector: str) -> Any: ...

    # --- Interactions ---

    @abstractmethod
    def click(self, locator: Any, *, dispatch: bool = False) -> None: ...

    @abstractmethod
    def fill(self, locator: Any, text: str) -> None: ...

    @abstractmethod
    def type(self, locator: Any, text: str, *, delay_ms: int = 0) -> None: ...

    def humanized_click(
        self,
        page: Any,
        locator: Any,
        behavior: Behavior,
        runtime: BehaviorRuntime,
    ) -> None:
        """Humanized click. Default falls back to plain click().

        Drivers with native humanization (e.g. nodriver's element.click,
        Camoufox with humanize=True) or Playwright-level helpers (see
        behavior.humanized_click) should override this.
        """
        self.click(locator)

    def humanized_type(
        self,
        page: Any,
        locator: Any,
        text: str,
        behavior: Behavior,
        runtime: BehaviorRuntime,
    ) -> None:
        """Humanized type. Default falls back to plain type().

        Override to use behavior.humanized_type or a driver-native path.
        """
        self.type(locator, text)

    @abstractmethod
    def press(self, locator: Any, key: str) -> None: ...

    @abstractmethod
    def press_focused(self, page: Any, key: str) -> None: ...

    @abstractmethod
    def select_option(self, locator: Any, value: str) -> None: ...

    @abstractmethod
    def set_checked(self, locator: Any, checked: bool) -> None: ...

    @abstractmethod
    def dispatch_event(self, locator: Any, event: str) -> None: ...

    # --- Navigation / waiting ---

    @abstractmethod
    def goto(self, page: Any, url: str, wait_until: str) -> None: ...

    @abstractmethod
    def wait_for_load(self, page: Any, state: str, timeout_ms: int) -> None: ...

    @abstractmethod
    def wait_for_state(self, locator: Any, state: str, timeout_ms: int) -> None: ...

    # --- Read / capture ---

    @abstractmethod
    def text_content(self, locator: Any) -> str | None: ...

    @abstractmethod
    def input_value(self, locator: Any) -> str: ...

    @abstractmethod
    def get_attribute(self, locator: Any, name: str) -> str | None: ...

    @abstractmethod
    def count(self, locator: Any) -> int: ...

    @abstractmethod
    def first(self, locator: Any) -> Any: ...

    @abstractmethod
    def nth(self, locator: Any, index: int) -> Any: ...

    @abstractmethod
    def all(self, locator: Any) -> list[Any]: ...

    @abstractmethod
    def child(self, locator: Any, selector: str) -> Any: ...

    @abstractmethod
    def evaluate(self, target: Any, script: str) -> Any: ...

    @abstractmethod
    def content(self, page: Any) -> str: ...

    @abstractmethod
    def page_url(self, page: Any) -> str: ...

    @abstractmethod
    def screenshot(self, page: Any, path: Path) -> None: ...

    @abstractmethod
    def expect_download(
        self, page: Any, trigger: Callable[[], None], output: Path
    ) -> Path: ...

    @abstractmethod
    def enter_frame(self, locator: Any) -> Any: ...

    # --- Composite waits ---

    def wait_for_stable_text(
        self, locator: Any, quiet_ms: int, timeout_ms: int
    ) -> str | None:
        """Wait until textContent stops changing for ``quiet_ms``.

        Returns the final text, or ``None`` on timeout.

        Default implementation polls from Python — each iteration crosses
        the transport. On Chromium/CDP this is a distinctive repeated
        ``Runtime.callFunctionOn`` pattern that Runtime-traffic detectors
        can fingerprint. Drivers with an in-page runtime should override
        so the stability detection runs inside the page.
        """
        poll_s = 0.25
        quiet_s = quiet_ms / 1000.0
        deadline = time.monotonic() + timeout_ms / 1000.0
        last_text = self.text_content(locator) or ""
        last_change = time.monotonic()
        while time.monotonic() < deadline:
            time.sleep(poll_s)
            text = self.text_content(locator) or ""
            now = time.monotonic()
            if text != last_text:
                last_text, last_change = text, now
            elif now - last_change >= quiet_s:
                return text
        return None
