"""Signals that a page needs a human: selectors, markup patterns and phrases."""

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
    "#px-captcha",
    '[id^="px-captcha"]',
    'iframe[src*="px-cdn"]',
    'iframe[src*="perimeterx"]',
    'form[action*="validateCaptcha" i]',
    'iframe[src*="captcha-delivery.com"]',
)

# A page needs a human only for a real credential prompt, a live bot challenge or
# an explicit interstitial — a bare "sign in" link is ordinary page furniture.
PASSWORD_INPUT_PATTERN = r"<input[^>]*type\s*=\s*[\"']?password"
CHALLENGE_IFRAME_PATTERN = r"<iframe[^>]*(?:hcaptcha|recaptcha|px-cdn|perimeterx)"
CHALLENGE_MARKERS = (
    "cf-challenge",
    "challenge-platform",
    "px-captcha",
    "validatecaptcha",
    "captcha-delivery.com",
)
# Matched against ``probe.fold_text`` output, so written lowercase without accents.
# Never a bare "continue shopping": every cart page says it.
INTERSTITIAL_PHRASES = (
    "verify you are human",
    "access denied",
    "unusual traffic",
    "press and hold",
    "robot or human",
    "click the button below to continue shopping",
    "robot o humano",
    "manten presionado",
    "mantenga presionado",
    "verifica que eres humano",
    "haz clic en el boton de abajo para continuar comprando",
)
