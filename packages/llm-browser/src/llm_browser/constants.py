"""Shared constants for llm-browser."""

import re
from pathlib import Path
from typing import Literal, get_args

DEFAULT_STATE_DIR = Path("/tmp/llm-browser")

DRIVER_ENV_VAR = "LLM_BROWSER_DRIVER"

LOGGER_NAME = "llm_browser"

DEFAULT_WAIT_TIMEOUT_MS = 3_000

# nodriver has no CDP wait for visibility/detachment, so those states are
# polled; 100ms keeps Runtime traffic low without feeling laggy.
NODRIVER_POLL_INTERVAL_S = 0.1

DEFAULT_URL_SCHEMES = ("http", "https")

REDACTED = "***"

OUTPUT_ACTIONS = frozenset({"read", "parse", "dom"})

EXTRA_SAFE_ATTRS = frozenset({"href", "src", "title"})

XHIGH_ATTRS = frozenset(
    {"id", "alt", "title", "role", "type", "name", "value", "placeholder"}
)

URL_ATTRS = ("src", "srcset", "href")

KILL_TAGS = ["svg", "object", "embed", "applet"]

STRUCTURAL_TAGS = frozenset({"div", "span", "section"})

WHITESPACE_PRESERVE_TAGS = frozenset({"pre", "textarea"})

DATA_URI_PATTERN = re.compile(r"^(data:[^;,]+)[;,].*$", re.S)

# --- Page probe / human detection ---

PROBE_TEXT_MAX_CHARS = 20_000

PASSWORD_SELECTOR = 'input[type="password"]'

CHALLENGE_SELECTORS = (
    'iframe[src*="hcaptcha"]',
    'iframe[src*="recaptcha"]',
    'iframe[title*="recaptcha" i]',
    ".h-captcha",
    ".g-recaptcha",
    "#cf-challenge",
    '[id*="cf-chl"]',
    '[class*="cf-challenge"]',
    "#challenge-form",
    "#challenge-running",
    ".cf-turnstile",
)

# Substituted into ``js/page_probe.js``; no name is a substring of another, so
# the replacements are order-independent.
PROBE_SELECTOR_PLACEHOLDER = "PROBE_SELECTOR_JSON"
PROBE_PASSWORD_PLACEHOLDER = "PASSWORD_SELECTOR_JSON"
PROBE_CHALLENGE_PLACEHOLDER = "CHALLENGE_SELECTOR_JSON"
PROBE_MAX_CHARS_PLACEHOLDER = "MAX_CHARS_INT"

# A page needs a human only for a real credential prompt, a live bot challenge or
# an explicit interstitial — a bare "sign in" link is ordinary page furniture.
PASSWORD_INPUT_PATTERN = r"<input[^>]*type\s*=\s*[\"']?password"
CHALLENGE_IFRAME_PATTERN = r"<iframe[^>]*(?:hcaptcha|recaptcha)"
CHALLENGE_MARKERS = ("cf-challenge", "challenge-platform")
INTERSTITIAL_PHRASES = ("verify you are human", "access denied", "unusual traffic")

# --- Extract specs (``"child selector@attribute"``) ---

EXTRACT_ATTRIBUTE_SEPARATOR = "@"
DEFAULT_EXTRACT_ATTRIBUTE = "textContent"
DEFAULT_EXTRACT_FIELD = "text"

# --- Flow sources ---

FlowFormat = Literal["yaml", "json"]

FLOW_FORMATS: tuple[FlowFormat, ...] = get_args(FlowFormat)

DEFAULT_FLOW_FORMAT: FlowFormat = "yaml"

#: Suffixes that pick a non-default format; anything else is YAML.
FLOW_FORMAT_BY_SUFFIX: dict[str, FlowFormat] = {".json": "json"}
