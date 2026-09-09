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
