# One importable translation is what lets test_front_ends.py prove CLI and pytest agree.

import pytest

from llm_browser_conformance.runner import Result
from llm_browser_conformance.scenario import Outcome

# What each verdict looks like in a pytest run. ``XPASS`` is a failure on
# purpose: a gap that has closed must not read as success.
PYTEST_VERDICT: dict[Outcome, str] = {
    Outcome.PASS: "passed",
    Outcome.XFAIL: "xfailed",
    Outcome.SKIP: "skipped",
    Outcome.FAIL: "failed",
    Outcome.XPASS: "failed",
}


def check(result: Result) -> None:
    if result.outcome is Outcome.SKIP:
        pytest.skip(result.detail)
    if result.outcome is Outcome.XFAIL:
        pytest.xfail(result.detail)
    assert not result.outcome.is_failure, result.detail
