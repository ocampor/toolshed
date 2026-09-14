"""What `explore_many` costs and what it answers: one page call, every target."""

import json
from types import SimpleNamespace

import pytest

from llm_browser import constants
from llm_browser.explore import explore_many
from llm_browser.explore_models import ExploreTarget, Intent, Stability, Verdict


def element(**over: object) -> dict[str, object]:
    """One target's first-match read, as the page hands it back."""
    first = {
        "tag": "a",
        "text": "Senior engineer",
        "visible": True,
        "enabled": True,
        "in_viewport": True,
        "stable": True,
        "pointer_events": True,
        "why_not": [],
    }
    locators = {"tag": "a", "testid_attribute": "data-testid", "testid": "mission"}
    return {
        "first": {**first, **over},
        "locators": locators,
        "since_navigation_ms": 900,
    }


def answer(selector: str, count: int, **over: object) -> dict[str, object]:
    return {
        "selector": selector,
        "count": count,
        "sample": [],
        "text_chars": 0,
        "element": element() if count else None,
        "since_call_ms": 40,
        **over,
    }


class FakeSession:
    """A session that answers one page call with what the page would have."""

    def __init__(self, answers: list[dict[str, object]], counts: dict[str, int]):
        self.answers = answers
        self.counts = counts
        self.scripts: list[str] = []
        self.timeouts: list[int | None] = []
        self.counted: list[str] = []
        self.driver = SimpleNamespace(supports_role_selector=True)

    def evaluate_document(
        self, script: str, timeout_ms: int | None = None
    ) -> list[dict[str, object]]:
        self.scripts.append(script)
        self.timeouts.append(timeout_ms)
        return self.answers

    def verified_candidates(
        self, proposals: list[str], accepted: set[int]
    ) -> list[str]:
        from llm_browser import explore

        return explore.verified_candidates(self, proposals, accepted)

    def count_of(self, selector: str) -> int:
        self.counted.append(selector)
        return self.counts.get(selector, 0)


def test_a_batch_is_one_page_call_whatever_it_asks_for() -> None:
    """The whole point: three targets cost one evaluation, not three waits."""
    session = FakeSession(
        [answer(".card", 3), answer("#search", 1), answer(".gone", 0)],
        counts={'[data-testid="mission"]': 3},
    )

    results = explore_many(
        session,
        [
            ExploreTarget(selector=".card"),
            ExploreTarget(selector="#search", intent=Intent.FILL),
            ExploreTarget(selector=".gone"),
        ],
    )

    assert len(session.scripts) == 1
    assert [result.count for result in results] == [3, 1, 0]
    # Answers come back in the order asked, so a caller can zip them with its
    # own targets.
    assert [result.verdict for result in results] == [
        Verdict.OK,
        Verdict.OK,
        Verdict.MISSING,
    ]
    assert results[0].candidates == ['[data-testid="mission"]']
    assert results[0].since_navigation_ms == 900
    assert results[0].since_call_ms == 40
    assert results[0].stability is Stability.OTHER
    assert results[2].first is None and results[2].candidates == []


def test_the_sample_and_its_empty_fields_come_back_per_target() -> None:
    session = FakeSession(
        [
            answer(
                ".row",
                2,
                sample=[
                    {"title": "Alpha", "href": None},
                    {"title": "Beta", "href": None},
                ],
                text_chars=11,
            )
        ],
        counts={},
    )

    (result,) = explore_many(
        session,
        [ExploreTarget(selector=".row", extract={"title": "a", "href": "a@href"})],
    )

    assert [row["title"] for row in result.sample] == ["Alpha", "Beta"]
    assert result.empty_fields == ["href"]
    assert result.text_chars == 11
    # The page reads the fields, so it is told the resolved spec.
    spec = {"title": {"child_selector": "a", "attribute": "textContent"}}
    assert json.dumps(spec)[1:-1] in session.scripts[0]


def test_a_timeout_is_a_page_with_none_of_them_on_it() -> None:
    """The wait is the batch's: when it runs out every target is a count of
    zero rather than an exception, the same answer `explore` gives."""
    session = FakeSession([answer(".a", 0), answer(".b", 0)], counts={})

    results = explore_many(
        session,
        [ExploreTarget(selector=".a"), ExploreTarget(selector=".b")],
        timeout_ms=50,
    )

    assert [result.count for result in results] == [0, 0]
    assert all(result.verdict is Verdict.MISSING for result in results)
    assert session.counted == []


def test_a_selector_the_page_cannot_parse_answers_for_itself_only() -> None:
    """A typo is the author's, but it is one target's: the eleven answers the
    page already computed are not thrown away with it."""
    session = FakeSession(
        [answer("div >", 0, invalid=True), answer(".card", 3)], counts={}
    )

    refused, cards = explore_many(
        session,
        [ExploreTarget(selector="div >"), ExploreTarget(selector=".card")],
    )

    assert refused.error == "not css"
    assert refused.count == 0 and refused.verdict is Verdict.MISSING
    assert refused.first is None and refused.candidates == []
    assert cards.count == 3 and cards.verdict is Verdict.OK and cards.error is None


def test_the_driver_is_given_longer_than_the_wait_it_is_running() -> None:
    """The wait happens inside the evaluate, so the evaluate outlives it — or
    the driver's own default ends the call before the answer arrives."""
    session = FakeSession([answer(".a", 1), answer(".b", 1)], counts={})

    explore_many(
        session,
        [ExploreTarget(selector=".a"), ExploreTarget(selector=".b")],
        timeout_ms=45_000,
    )

    settles = 2 * constants.EXPLORE_STABLE_DELAY_MS
    assert session.timeouts == [45_000 + settles + constants.EXPLORE_MANY_MARGIN_MS]


def test_more_targets_than_one_page_call_takes_is_refused() -> None:
    """Each target settles in turn, so a hundred of them is a page call nobody
    sized a timeout for."""
    session = FakeSession([], counts={})
    targets = [
        ExploreTarget(selector=f".c{index}")
        for index in range(constants.EXPLORE_MANY_MAX_TARGETS + 1)
    ]

    with pytest.raises(ValueError, match="at most 20 targets"):
        explore_many(session, targets)
    assert session.scripts == []


def test_no_targets_is_no_page_call() -> None:
    session = FakeSession([], counts={})

    assert explore_many(session, []) == []
    assert session.scripts == []
