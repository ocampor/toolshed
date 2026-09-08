"""Shared constants for llm-browser."""

from pathlib import Path

DEFAULT_STATE_DIR = Path("/tmp/llm-browser")

DRIVER_ENV_VAR = "LLM_BROWSER_DRIVER"

LOGGER_NAME = "llm_browser"

REDACTED = "***"

# Actions whose result is kept in ``FlowSuccess.outputs``.
OUTPUT_ACTIONS = frozenset({"read", "parse", "dom"})
