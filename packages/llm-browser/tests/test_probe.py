"""Tests for page probing and the human-needed heuristic."""

import json
from unittest.mock import MagicMock

import pytest

from llm_browser import probe
from llm_browser.constants import CHALLENGE_SELECTORS, PASSWORD_SELECTOR
from llm_browser.models import PageProbe
from llm_browser.scripts import page_probe_js
from llm_browser.selectors import XpathSelector
from llm_browser.session import BrowserSession

PROBE_CASES = [
    (
        PageProbe(password_visible=False, text="Quarterly revenue rose 4%\nSign in"),
        False,
    ),
    (PageProbe(password_visible=True, text="Sign in to continue"), True),
    (PageProbe(text="Please verify you are human before continuing"), True),
    (PageProbe(text="Log in to comment on this story"), False),
    (PageProbe(challenge=True, text="One moment please"), True),
    (PageProbe(), False),
]

MARKUP_CASES = [
    ('<form><input type="password" name="pw"></form>', True),
    ("<INPUT TYPE=PASSWORD>", True),
    ('<div id="cf-challenge"></div>', True),
    ('<script src="/cdn-cgi/challenge-platform/h/b/orchestrate"></script>', True),
    ('<iframe src="https://hcaptcha.com/captcha/v1"></iframe>', True),
    (
        '<iframe title="recaptcha" src="https://google.com/recaptcha/api2"></iframe>',
        True,
    ),
    ("<p>Please verify you are human before continuing</p>", True),
    ("<h1>Access Denied</h1>", True),
    ("<p>We detected unusual traffic from your network</p>", True),
    ('<a href="/login">Sign in</a>', False),
    ("<p>Log in to comment on this story</p>", False),
    ("<article><h1>Quarterly revenue rose 4%</h1></article>", False),
    ("", False),
    ("<p>A robot vacuum review</p>", False),
]


@pytest.mark.parametrize(("page_probe", "expected"), PROBE_CASES)
def test_human_needed(page_probe: PageProbe, expected: bool) -> None:
    assert probe.human_needed(page_probe) is expected


@pytest.mark.parametrize(("markup", "expected"), MARKUP_CASES)
def test_human_needed_from_a_failure_snapshot(markup: str, expected: bool) -> None:
    assert probe.human_needed(probe.probe_from_markup(markup)) is expected


# --- script substitution ---


def test_page_probe_js_substitutes_every_placeholder() -> None:
    source = page_probe_js("main .body", 500)
    assert "PROBE_SELECTOR_JSON" not in source
    assert json.dumps("main .body") in source
    assert json.dumps(PASSWORD_SELECTOR) in source
    assert json.dumps(", ".join(CHALLENGE_SELECTORS)) in source
    assert ".slice(0, 500)" in source


def test_page_probe_js_without_a_selector() -> None:
    assert "const selector = null;" in page_probe_js(None, 10)


# --- session.probe ---


@pytest.fixture
def session(tmp_path: object) -> BrowserSession:
    s = BrowserSession(state_dir=tmp_path)  # type: ignore[arg-type]
    s._page = MagicMock()
    return s


def test_probe_maps_the_evaluate_result(session: BrowserSession) -> None:
    session.driver = MagicMock()
    session.driver.evaluate.return_value = {
        "password_visible": True,
        "challenge": False,
        "text": "Sign in to continue",
        "selector_text": "Sign in",
    }
    result = session.probe("form.login", max_chars=64)
    script = session.driver.evaluate.call_args.args[1]
    assert session.driver.evaluate.call_args.args[0] is session._page
    assert json.dumps("form.login") in script
    assert result == PageProbe(
        password_visible=True,
        challenge=False,
        text="Sign in to continue",
        selector_text="Sign in",
    )


def test_probe_on_an_empty_result_is_all_defaults(session: BrowserSession) -> None:
    session.driver = MagicMock()
    session.driver.evaluate.return_value = None
    assert session.probe() == PageProbe()


def test_probe_rejects_a_selector_with_no_css_form(session: BrowserSession) -> None:
    session.driver = MagicMock()
    with pytest.raises(ValueError, match="no CSS form"):
        session.probe(XpathSelector(xpath="//div"))
