"""Shared constants for llm-browser."""

from pathlib import Path

DEFAULT_STATE_DIR = Path("/tmp/llm-browser")

DRIVER_ENV_VAR = "LLM_BROWSER_DRIVER"

NTFY_URL_ENV_VAR = "LLM_BROWSER_NTFY_URL"
NTFY_TOKEN_ENV_VAR = "LLM_BROWSER_NTFY_TOKEN"
VNC_URL_ENV_VAR = "LLM_BROWSER_VNC_URL"

NOTIFY_TIMEOUT_S = 10.0

# Short bounded probe so `wait_for`'s cadence is set by poll_ms alone.
PROBE_TIMEOUT_MS = 500
