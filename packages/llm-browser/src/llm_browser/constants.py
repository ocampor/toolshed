"""Shared constants for llm-browser."""

import datetime
import decimal
import re
from pathlib import Path

DEFAULT_STATE_DIR = Path("/tmp/llm-browser")

DRIVER_ENV_VAR = "LLM_BROWSER_DRIVER"

LOGGER_NAME = "llm_browser"

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

# What a Playwright-family driver says when a read raced a navigation.
DESTROYED_CONTEXT_MESSAGE = "Execution context was destroyed"

DEFAULT_URL_SCHEMES = ("http", "https")

# What a `type` step's `delay` may be, said once so a bad pair reads as one
# error instead of two union failures.
DELAY_SHAPE = "delay must be a non-negative int, or [min_ms, max_ms] with min <= max"

REDACTED = "***"

# Why a step a ``when:`` predicate gated shows up in ``FlowSuccess.skipped``.
WHEN_SKIP_REASON = "when condition not satisfied"

# Every action whose result the flow runner keeps in ``outputs``.
OUTPUT_ACTIONS = frozenset({"read", "parse", "dom", "screenshot", "download"})

EXTRA_SAFE_ATTRS = frozenset({"href", "src", "title"})

XHIGH_ATTRS = frozenset(
    {"id", "alt", "title", "role", "type", "name", "value", "placeholder"}
)

URL_ATTRS = ("src", "srcset", "href")

KILL_TAGS = ["svg", "object", "embed", "applet"]

STRUCTURAL_TAGS = frozenset({"div", "span", "section"})

WHITESPACE_PRESERVE_TAGS = frozenset({"pre", "textarea"})

DATA_URI_PATTERN = re.compile(r"^(data:[^;,]+)[;,].*$", re.S)

# An outerHTML rooted at one of these is a whole document to lxml.
DOCUMENT_ROOT_PATTERN = re.compile(r"\s*<(html|body)(?=[\s/>]|$)", re.I)

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

# Bounds the hit test a humanized click runs between its move and its
# mouse-down, so a detached target cannot buy the driver's 30 s default while
# the pointer sits pressed-ready on the page.
HIT_TEST_TIMEOUT_MS = 1_000

# Substituted into ``js/hit_test.js``.
HIT_POINT_PLACEHOLDER = "HIT_POINT_JSON"
HIT_TEXT_MAX_PLACEHOLDER = "HIT_TEXT_MAX_INT"

# Substituted into ``js/extract_rows.js``.
EXTRACT_PROPERTIES_PLACEHOLDER = "EXTRACT_PROPERTIES_JSON"

# Substituted into ``js/select_option.js``.
SELECT_VALUE_PLACEHOLDER = "SELECT_VALUE_JSON"

# A page needs a human only for a real credential prompt, a live bot challenge or
# an explicit interstitial — a bare "sign in" link is ordinary page furniture.
PASSWORD_INPUT_PATTERN = r"<input[^>]*type\s*=\s*[\"']?password"
CHALLENGE_IFRAME_PATTERN = r"<iframe[^>]*(?:hcaptcha|recaptcha)"
CHALLENGE_MARKERS = ("cf-challenge", "challenge-platform")
INTERSTITIAL_PHRASES = ("verify you are human", "access denied", "unusual traffic")

# --- Extract specs (``"child selector@attribute"``) ---

# Read as ``el[name]``; every other name is an HTML attribute.
EXTRACT_PROPERTIES = (
    "childElementCount",
    "innerHTML",
    "innerText",
    "outerHTML",
    "tagName",
    "textContent",
    "value",
)

EXTRACT_ATTRIBUTE_SEPARATOR = "@"
DEFAULT_EXTRACT_ATTRIBUTE = "textContent"
DEFAULT_EXTRACT_FIELD = "text"

# How many matches ``BrowserSession.explore`` reads: enough to see whether the
# rows differ from each other, few enough to stay one round-trip per row.
EXPLORE_SAMPLE_ROWS = 3

EXPLORE_LIMITS_PLACEHOLDER = "EXPLORE_LIMITS_JSON"
EXPLORE_TEXT_MAX_CHARS = 120
EXPLORE_COVER_TEXT_MAX_CHARS = 60
# Long enough for a transition or a reflow to show up in the second rect,
# short enough to sit inside one `explore` without being felt.
EXPLORE_STABLE_DELAY_MS = 100
EXPLORE_MAX_CANDIDATES = 3
EXPLORE_NESTED_TEXT_MAX_CHARS = 40
EXPLORE_MAX_NESTED_CONTROLS = 5
# How much of each sampled field the sample keeps. Reading the whole of every
# row is what `read` is for.
EXPLORE_SAMPLE_CHARS = 200
# How far up from the first match a test id still names it.
EXPLORE_ANCESTOR_LEVELS = 3
TESTID_ATTRIBUTES = ("data-testid", "data-testing-id")

# Reasons a click would miss that the drivers handle themselves: every one of
# them scrolls the target into view first.
EXPLORE_NON_BLOCKING = ("offscreen",)

EXPLORE_ELEMENT_PLACEHOLDER = "EXPLORE_ELEMENT_JS"
EXPLORE_BATCH_PLACEHOLDER = "EXPLORE_BATCH_JSON"
# How often the batch wait looks again, in the page rather than over the wire.
EXPLORE_MANY_POLL_MS = 100
# One page call reads every target in turn, each settling for
# EXPLORE_STABLE_DELAY_MS, so a batch has to stay small enough to finish inside
# a driver timeout an author can reason about.
EXPLORE_MANY_MAX_TARGETS = 20
# What the batch evaluate is allowed on top of the wait and the settles:
# the round trip itself, plus the reads of every target's first match.
EXPLORE_MANY_MARGIN_MS = 5000

# --- Survey ---

SURVEY_LIMITS_PLACEHOLDER = "SURVEY_LIMITS_JSON"
SURVEY_COUNT_PLACEHOLDER = "COUNT_SELECTORS_JSON"
# How many named elements a survey reports. Enough to see what a page is made
# of, few enough to read in one go.
SURVEY_MAX_ITEMS = 60
SURVEY_MAX_LINK_SHAPES = 15
SURVEY_MAX_REPEATS = 10
SURVEY_TEXT_MAX_CHARS = 60
# What the page hands over before any ranking or grouping is applied. The
# output is capped again after it, so these only bound the transfer.
SURVEY_MAX_RAW_LANDMARKS = 400
SURVEY_MAX_RAW_REPEATS = 200
SURVEY_MAX_HREFS = 500
# Three of a kind is a pattern; two is a pair.
SURVEY_MIN_SIBLINGS = 3
# A build's numbering on the end of a class name: `card-0-2-3`, `title-17`,
# `css-1x2y3z`. What is left is what the next deploy will still call it. One
# pattern, applied on both sides: the page groups siblings by it and
# ``llm_browser.survey`` names the group by it.
CLASS_SUFFIX_PATTERN = r"(?:-(?:\d+|[A-Za-z0-9]*\d[A-Za-z0-9]*))+$"

# What counts as an element a click means something to, when no `onclick` and
# no `cursor: pointer` says so.
INTERACTIVE_TAGS = (
    "a",
    "button",
    "input",
    "select",
    "textarea",
    "label",
    "summary",
)
# The role a `role=` selector matches when the element spells out none.
IMPLICIT_ROLES = {"a": "link", "button": "button"}

INTERACTIVE_ROLES = (
    "button",
    "link",
    "tab",
    "menuitem",
    "checkbox",
    "option",
)

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
