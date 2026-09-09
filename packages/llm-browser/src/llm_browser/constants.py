"""Shared constants for llm-browser."""

import re
from pathlib import Path

DEFAULT_STATE_DIR = Path("/tmp/llm-browser")

DRIVER_ENV_VAR = "LLM_BROWSER_DRIVER"

LOGGER_NAME = "llm_browser"

REDACTED = "***"

OUTPUT_ACTIONS = frozenset({"read", "parse", "dom"})

EXTRA_SAFE_ATTRS = frozenset({"href", "src", "title"})

XHIGH_ATTRS = frozenset(
    {"id", "href", "alt", "title", "role", "type", "name", "value", "placeholder"}
)

IFRAME_XHIGH_ATTRS = frozenset({"title"})

URL_ATTRS = ("src", "srcset", "href")

KILL_TAGS = ["svg", "object", "embed", "applet"]

STRUCTURAL_TAGS = frozenset({"div", "span", "section"})

WHITESPACE_PRESERVE_TAGS = frozenset({"pre", "textarea"})

DATA_URI_PATTERN = re.compile(r"^(data:[^;,]+)[;,].*$", re.S)
