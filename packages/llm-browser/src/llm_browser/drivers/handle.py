"""Driver connection state and optional-dependency loading."""

import importlib
from types import ModuleType

from pydantic import BaseModel


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
