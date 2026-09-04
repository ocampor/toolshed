"""Shared constants for llm-browser."""

from pathlib import Path

from llm_browser.behavior import Jitter

DEFAULT_STATE_DIR = Path("/tmp/llm-browser")

DRIVER_ENV_VAR = "LLM_BROWSER_DRIVER"

# Pause between wheel ticks of a ``scroll`` step when the step declares none.
DEFAULT_SCROLL_PAUSE = Jitter(min_ms=300, max_ms=1200)
