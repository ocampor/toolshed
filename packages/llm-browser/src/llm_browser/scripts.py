"""In-page JavaScript loaded from ``js/``."""

from functools import lru_cache
from pathlib import Path

JS_DIR = Path(__file__).parent / "js"


@lru_cache(maxsize=None)
def load_script(name: str) -> str:
    """Return the source of ``js/<name>.js``."""
    return (JS_DIR / f"{name}.js").read_text()


def extract_rows_js() -> str:
    """``(rows, spec) => list[dict]`` — read every field off every row."""
    return load_script("extract_rows")
