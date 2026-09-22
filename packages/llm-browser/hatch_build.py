"""Build hook: the generated reference is written into the wheel, not into git.

``src/llm_browser/docgen.py`` is loaded by path rather than imported, so the
build environment needs griffe and griffe2md but none of the package's own
runtime dependencies.
"""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


def load_by_path(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReferenceDocsHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        source = Path(self.root) / "src"
        docgen = load_by_path(source / "llm_browser" / "docgen.py")
        docgen.write_reference(source)
