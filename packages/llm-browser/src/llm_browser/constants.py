"""Shared constants for llm-browser."""

import datetime
import decimal
import re
from pathlib import Path

DEFAULT_STATE_DIR = Path("/tmp/llm-browser")

DRIVER_ENV_VAR = "LLM_BROWSER_DRIVER"

LOGGER_NAME = "llm_browser"

# --- Packaged Claude Code skill ---

SKILL_NAME = "llm-browser-flows"

SKILL_DIR_NAME = "skill"

SKILL_FILENAME = "SKILL.md"

DEFAULT_WAIT_TIMEOUT_MS = 3_000

# How long ``find`` and the input methods wait for their element.
DEFAULT_FIND_TIMEOUT_MS = 10_000

DEFAULT_POLL_INTERVAL_MS = 500

# How long an element's text has to stay put for the ``stable`` wait state.
DEFAULT_SETTLE_MS = 1_500

# A Playwright read still needs a timeout — `timeout=0` there means *no*
# timeout — so a now-read gets one long enough for a slow round-trip and short
# enough not to be a wait.
READ_TIMEOUT_MS = 250

# An explicit wait sleeps ``interval`` ± this fraction: a fixed 500ms cadence is
# itself a fingerprint.
POLL_JITTER_RATIO = 0.3

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

# --- YAML schema types ---

# The only names a schema `type:` string may use; see `schema_types.py`.
SCHEMA_TYPE_NAMES = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "Decimal": decimal.Decimal,
    "date": datetime.date,
    "datetime": datetime.datetime,
}
