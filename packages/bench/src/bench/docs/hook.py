"""Hatch build hook: the generated reference is written into the wheel, not into git.

``src/<package>/docgen.py`` is loaded by path rather than imported, so the build
environment needs the ``docs`` extra but none of the consumer's own runtime
dependencies.
"""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

# First, so a missing extra is named before hatchling is ever reached.
from bench.docs.files import write_reference

# isort: split
from hatchling.builders.hooks.plugin.interface import BuildHookInterface


def load_by_path(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReferenceDocsHook(BuildHookInterface):  # type: ignore[type-arg]
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        source = Path(self.root) / "src"
        docgen = load_by_path(source / self.config["package"] / "docgen.py")
        write_reference(docgen.REFERENCE, source)
