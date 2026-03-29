"""JavaScript snippet loader for browser automation."""

from functools import lru_cache

from llm_browser.constants import JS_DIR


@lru_cache(maxsize=None)
def load_js(name: str) -> str:
    """Load a JS snippet by filename (without extension)."""
    return (JS_DIR / f"{name}.js").read_text()
