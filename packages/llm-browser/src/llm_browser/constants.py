"""Shared constants for llm-browser."""

import re
from pathlib import Path

DEFAULT_STATE_DIR = Path("/tmp/llm-browser")
JS_DIR = Path(__file__).parent / "js"
CDP_STARTUP_TIMEOUT = 10.0
CDP_URL_RE = re.compile(r"DevTools listening on (ws://\S+)")
