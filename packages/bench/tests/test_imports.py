import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parents[1] / "src"


def import_bare(module: str) -> subprocess.CompletedProcess[str]:
    """`-S` skips site-packages, so griffe is as absent as in a bare install."""
    code = f"import sys; sys.path.insert(0, {str(SRC)!r}); import {module}"
    return subprocess.run([sys.executable, "-S", "-c", code], capture_output=True, text=True)


@pytest.mark.parametrize("module", ["bench", "bench.docs", "bench.docs.sections"])
def test_bare_install_imports(module: str) -> None:
    assert import_bare(module).returncode == 0


@pytest.mark.parametrize("module", ["bench.docs.render", "bench.docs.files", "bench.docs.hook"])
def test_bare_install_names_the_extra(module: str) -> None:
    result = import_bare(module)
    assert result.returncode == 1
    assert "ocampor-bench[docs]" in result.stderr
    assert "ModuleNotFoundError" not in result.stderr
