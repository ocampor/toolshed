"""``expect`` / ``pick``: what a step's selector should match, and which match
it acts on."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from llm_browser.actions import execute_action
from llm_browser.drivers.base import Driver
from llm_browser.flows import load_flow_document, run_flow
from llm_browser.models import (
    FlowData,
    FlowError,
    FlowSuccess,
    match_rule_of,
    validate_step,
)
from llm_browser.results import AcceptedMatch, ErrorResult, ParsedResult
from llm_browser.selectors import (
    MANY,
    SINGLE,
    Match,
    MatchCountError,
    MatchError,
    MatchRule,
    PickRangeError,
    match_elements,
)
from llm_browser.session import BrowserSession
from llm_browser.steps import resolve_step_templates

PRICES = ["£45.17", "£53.74", "£23.21", "£12.00", "£9.99", "£1.50", "£7.77"]


def fake_driver(found: int) -> MagicMock:
    """A page where every selector matches ``found`` elements, each reading as
    one of ``PRICES``."""
    driver = MagicMock(spec=Driver)
    driver.resolve.side_effect = lambda page, selector: ("locator", selector)
    driver.count.side_effect = lambda locator: found
    driver.first.side_effect = lambda locator: ("first", locator)
    driver.nth.side_effect = lambda locator, index: ("nth", locator, index)
    # A page with no match has nothing visible, which is what makes a wait for
    # one time out.
    driver.is_visible.side_effect = lambda locator: found > 0
    driver.text_content.side_effect = lambda locator: PRICES[locator[2]]
    driver.extract_rows.side_effect = lambda locator, spec, exclude=(): [
        {"text": price} for price in PRICES[:found]
    ]
    return driver


def page_session(tmp_path: Path, found: int) -> BrowserSession:
    session = BrowserSession(state_dir=tmp_path, capture="none")
    session.driver = fake_driver(found)
    session._page = MagicMock()
    return session


def read_step(**extra: Any) -> dict[str, Any]:
    return {"name": "price", "action": "read", "selector": "p.price_color", **extra}


def run_steps(
    session: BrowserSession, steps: list[dict[str, Any]], **kwargs: Any
) -> Any:
    flow = load_flow_document({"steps": steps})
    return run_flow(session, flow, kwargs.pop("data", {}), **kwargs)


# --- load-time validation ---


@pytest.mark.parametrize(
    "step",
    [
        {"action": "click", "selector": "#a"},
        {"action": "click", "selector": "#a", "expect": 1},
        {"action": "click", "selector": "#a", "expect": 7, "pick": "first"},
        {"action": "click", "selector": "#a", "expect": "many", "pick": 2},
        {"action": "read", "selector": "#a"},
        {"action": "read", "selector": "#a", "expect": 1},
        {"action": "read", "selector": "#a", "expect": 3, "pick": "last"},
        {"action": "press", "key": "Enter"},
        {"action": "screenshot"},
        {"action": "screenshot", "selector": "#a", "expect": 2, "pick": 0},
        {"action": "pick", "selector": "#a", "value": "x", "expect": 1},
    ],
)
def test_a_valid_match_rule_loads(step: dict[str, Any]) -> None:
    assert validate_step({"name": "s", **step}) is not None


def test_a_pick_step_keeps_its_action_default_expect() -> None:
    step = validate_step(
        {"name": "s", "action": "pick", "selector": "#a", "value": "x", "pick": "first"}
    )
    assert match_rule_of(step) == MatchRule(expect="many", pick="first")


@pytest.mark.parametrize(
    "step",
    [
        {"action": "click", "selector": "#a", "expect": 3},
        {"action": "click", "selector": "#a", "expect": 0},
        {"action": "click", "selector": "#a", "expect": "some"},
        {"action": "click", "selector": "#a", "pick": "middle"},
        {"action": "click", "selector": "#a", "pick": -1},
    ],
)
def test_a_bad_match_rule_is_rejected(step: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        validate_step({"name": "s", **step})


@pytest.mark.parametrize(
    "step",
    [
        {"action": "wait_for", "selector": "#a", "expect": 1},
        {"action": "wait_for", "selector": "#a", "expect": "many"},
        {"action": "wait_for", "selector": "#a", "pick": "first"},
        {"action": "press", "key": "Enter", "expect": 1},
        {"action": "press", "key": "Enter", "pick": "first"},
        {"action": "screenshot", "expect": "many"},
        {"action": "screenshot", "pick": 0},
    ],
)
def test_a_step_with_nothing_to_count_rejects_the_fields(step: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        validate_step({"name": "s", **step})


def test_the_fields_survive_the_template_round_trip() -> None:
    step = validate_step(
        {"name": "s", "action": "read", "selector": "{{ sel }}", "expect": 3, "pick": 2}
    )
    resolved = resolve_step_templates(step, FlowData.model_validate({"sel": "#a"}))
    assert (resolved.selector, resolved.expect, resolved.pick) == ("#a", 3, 2)


@pytest.mark.parametrize(
    "step",
    [{"action": "press", "key": "Enter"}, {"action": "screenshot"}],
)
def test_a_step_that_states_neither_survives_the_round_trip(
    step: dict[str, Any],
) -> None:
    """The round trip re-validates a dump, so a default that came back as a
    stated one would fail the step it just ran."""
    resolved = resolve_step_templates(
        validate_step({"name": "s", **step}), FlowData.model_validate({})
    )
    assert (resolved.expect, resolved.pick) == (None, None)


# --- the count check itself ---


@pytest.mark.parametrize(
    "found, rule, nth, accepted",
    [
        (1, SINGLE, None, None),
        (1, MANY, None, None),
        (1, MatchRule(1, "first"), 0, None),
        (7, MANY, None, None),
        (7, MatchRule(7), None, None),
        (7, MatchRule(1, "first"), 0, (1, 7, "first")),
        (7, MatchRule(1, "last"), 6, (1, 7, "last")),
        (7, MatchRule(1, 3), 3, (1, 7, 3)),
        (7, MatchRule(3, "first"), 0, (3, 7, "first")),
        (7, MatchRule("many", "last"), 6, None),
        (0, MANY, None, None),
    ],
)
def test_a_count_the_rule_allows(
    found: int,
    rule: MatchRule,
    nth: int | None,
    accepted: tuple[object, int, object] | None,
) -> None:
    driver = fake_driver(found)
    match = match_elements(driver, ("locator", "#a"), "#a", rule)
    assert match.nth == nth
    assert (
        None
        if match.accepted is None
        else (match.accepted.expected, match.accepted.found, match.accepted.picked)
    ) == accepted


@pytest.mark.parametrize(
    "found, rule",
    [
        (7, SINGLE),
        (7, MatchRule(3)),
        (0, SINGLE),
        (0, MatchRule(1, "first")),
        (2, MatchRule(3, "first")),
    ],
)
def test_a_count_the_rule_rejects(found: int, rule: MatchRule) -> None:
    with pytest.raises(MatchCountError):
        match_elements(fake_driver(found), ("locator", "#a"), "#a", rule)


@pytest.mark.parametrize(
    "found, rule, message",
    [
        (7, MatchRule(1, 7), "pick: 7 needs at least 8 matches"),
        (7, MatchRule("many", 9), "pick: 9 needs at least 10 matches"),
        (0, MatchRule("many", "last"), "pick: last needs at least 1 match"),
        (0, MatchRule("many", 0), "pick: 0 needs at least 1 match"),
    ],
)
def test_a_pick_the_page_does_not_reach_is_its_own_error(
    found: int, rule: MatchRule, message: str
) -> None:
    with pytest.raises(PickRangeError) as caught:
        match_elements(fake_driver(found), ("locator", "x"), "p.price_color", rule)
    assert str(caught.value) == f"{message} for 'p.price_color', found {found}"


def test_the_failure_reads_as_the_author_wrote_the_selector() -> None:
    with pytest.raises(MatchCountError) as caught:
        match_elements(fake_driver(7), ("locator", "x"), "p.price_color", SINGLE)
    assert str(caught.value) == "expected 1 element for 'p.price_color', found 7"
    assert caught.value.samples == PRICES[:3]


@pytest.mark.parametrize(
    "found, rule, wanted, unwanted",
    [
        (7, SINGLE, "tighten the selector", ""),
        (2, MatchRule(3, "first"), "not rendered yet", "tighten"),
        (0, SINGLE, "not rendered yet", "tighten"),
        (0, MatchRule("many", "last"), "lower pick", "tighten"),
    ],
)
def test_the_hint_points_the_way_the_count_went(
    found: int, rule: MatchRule, wanted: str, unwanted: str
) -> None:
    with pytest.raises(MatchError) as caught:
        match_elements(fake_driver(found), ("locator", "x"), "p.price_color", rule)
    assert wanted in caught.value.hint
    assert unwanted == "" or unwanted not in caught.value.hint


def test_a_sample_that_cannot_be_read_never_masks_the_failure() -> None:
    driver = fake_driver(7)

    def text_content(locator: Any) -> str:
        if locator[2] == 1:
            raise RuntimeError("element detached while sampling")
        return PRICES[locator[2]]

    driver.text_content.side_effect = text_content
    with pytest.raises(MatchCountError) as caught:
        match_elements(driver, ("locator", "x"), "p.price_color", SINGLE)
    assert caught.value.samples == [PRICES[0], "", PRICES[2]]


def test_a_wait_is_only_pre_empted_by_an_ambiguity() -> None:
    """Too few matches is what the wait that follows is for."""
    assert match_elements(
        fake_driver(0), ("locator", "#a"), "#a", SINGLE, waiting=True
    ) == Match(("locator", "#a"))
    with pytest.raises(MatchCountError):
        match_elements(fake_driver(7), ("locator", "#a"), "#a", SINGLE, waiting=True)


def test_a_many_rule_never_counts() -> None:
    driver = fake_driver(7)
    match_elements(driver, ("locator", "#a"), "#a", MANY)
    driver.count.assert_not_called()


# --- steps ---


def test_a_read_that_expected_one_row_reports_what_it_found(tmp_path: Path) -> None:
    session = page_session(tmp_path, 7)
    result = execute_action(session, validate_step(read_step(expect=1)))
    assert isinstance(result, ErrorResult)
    assert result.error == "MatchCountError"
    assert (result.expected, result.found) == (1, 7)
    assert result.samples == PRICES[:3]
    assert result.hint is not None and "pick: first" in result.hint


def test_a_pick_takes_the_row_it_names(tmp_path: Path) -> None:
    session = page_session(tmp_path, 7)
    result = execute_action(session, validate_step(read_step(expect=1, pick="first")))
    assert isinstance(result, ParsedResult)
    assert [row.model_dump() for row in result.rows if row] == [{"text": PRICES[0]}]
    assert result.accepted is not None
    assert (result.accepted.found, result.accepted.picked) == (7, "first")


def test_an_acting_step_still_fails_a_missing_element_on_the_wait(
    tmp_path: Path,
) -> None:
    """An acting step states no count, so a page without its element is the
    wait's timeout, the way every consumer keying on it expects."""
    step = validate_step(
        {"name": "go", "action": "click", "selector": "a.link", "timeout": 50}
    )
    result = execute_action(page_session(tmp_path, 0), step)
    assert isinstance(result, ErrorResult)
    assert result.error == "TimeoutError"
    assert result.hint == "element hidden, missing, or slow to render"


def test_a_read_that_expected_one_row_fails_on_an_empty_page(tmp_path: Path) -> None:
    """The count it waited for and never got, not the bare wait timeout."""
    result = execute_action(
        page_session(tmp_path, 0), validate_step(read_step(expect=1, timeout=50))
    )
    assert isinstance(result, ErrorResult)
    assert (result.error, result.found) == ("MatchCountError", 0)


@pytest.mark.parametrize(
    "rule", [{"expect": "many", "pick": 9}, {"expect": 3, "pick": 9}]
)
def test_a_read_whose_pick_is_out_of_range_says_which(
    tmp_path: Path, rule: dict[str, Any]
) -> None:
    result = execute_action(page_session(tmp_path, 7), validate_step(read_step(**rule)))
    assert isinstance(result, ErrorResult)
    assert (result.error, result.expected, result.found) == ("PickRangeError", None, 7)
    assert result.samples == PRICES[:3]
    assert result.hint is not None and "tighten" not in result.hint


def test_a_read_that_states_a_count_waits_for_it(tmp_path: Path) -> None:
    session = page_session(tmp_path, 1)
    counts = iter([0])
    session.driver.count.side_effect = lambda locator: next(counts, 1)
    result = execute_action(
        session, validate_step(read_step(expect=1, timeout=1000, name="price"))
    )
    assert isinstance(result, ParsedResult)
    assert [row.model_dump() for row in result.rows if row] == [{"text": PRICES[0]}]


@pytest.mark.parametrize(
    "rule, waits", [({}, False), ({"expect": 1}, True), ({"pick": "first"}, True)]
)
def test_only_a_read_that_states_a_count_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rule: dict[str, Any], waits: bool
) -> None:
    session = page_session(tmp_path, 1)
    waited = MagicMock()
    monkeypatch.setattr(session, "wait_for_element", waited)
    execute_action(session, validate_step(read_step(**rule)))
    assert waited.called is waits


@pytest.mark.parametrize("found", [7, 0])
def test_a_default_read_takes_every_row(tmp_path: Path, found: int) -> None:
    result = execute_action(page_session(tmp_path, found), validate_step(read_step()))
    assert isinstance(result, ParsedResult)
    assert len(result.rows) == found
    assert result.accepted is None


def test_a_click_picks_the_first_of_several(tmp_path: Path) -> None:
    session = page_session(tmp_path, 7)
    step = validate_step(
        {"name": "go", "action": "click", "selector": "a.link", "pick": "first"}
    )
    result = execute_action(session, step)
    assert result.ok
    assert result.accepted is not None and result.accepted.found == 7
    session.driver.click.assert_called_once()
    assert session.driver.click.call_args.args[0] == ("nth", ("locator", "a.link"), 0)


def test_a_click_on_several_elements_still_fails(tmp_path: Path) -> None:
    step = validate_step({"name": "go", "action": "click", "selector": "a.link"})
    result = execute_action(page_session(tmp_path, 7), step)
    assert isinstance(result, ErrorResult)
    assert result.error == "MatchCountError"


def test_a_dom_step_reads_the_match_it_picked(tmp_path: Path) -> None:
    session = page_session(tmp_path, 7)
    session.driver.evaluate.return_value = "<p>picked</p>"
    step = validate_step(
        {"name": "d", "action": "dom", "selector": "p.price_color", "pick": "last"}
    )
    execute_action(session, step)
    target = session.driver.evaluate.call_args.args[0]
    assert target == ("nth", ("locator", "p.price_color"), 6)


# --- what a run reports ---


REPEAT = {"over": "codes", "as": "code"}
REPEAT_BLOCK = {"name": "loop", "action": "repeat", **REPEAT}
CLICK = {
    "name": "go",
    "action": "click",
    "selector": "a.link",
    "pick": "first",
    "timeout": 50,
}


def repeat_block(step: dict[str, Any]) -> dict[str, Any]:
    return {**REPEAT_BLOCK, "steps": [step]}


@pytest.mark.parametrize(
    "steps, succeeds, warned, skipped",
    [
        ([read_step(expect=1, pick="first")], True, ["price"], []),
        (
            [read_step(expect=1, pick="first", repeat=REPEAT)],
            True,
            ["price[0]", "price[1]"],
            [],
        ),
        (
            [
                {
                    "name": "inner",
                    "action": "run-flow",
                    "flow": {"steps": [read_step(expect=1, pick="first")]},
                }
            ],
            True,
            ["inner/price"],
            [],
        ),
        ([CLICK], False, ["go"], []),
        ([{**CLICK, "optional": True}], True, ["go"], ["go"]),
        ([{**CLICK, "repeat": REPEAT}], False, ["go[0]"], []),
        (
            [repeat_block(read_step(expect=1, pick="first"))],
            True,
            ["loop/price[0]", "loop/price[1]"],
            [],
        ),
        ([repeat_block(CLICK)], False, ["loop/go[0]"], []),
    ],
)
def test_a_run_names_every_step_whose_pick_took_a_mismatch(
    tmp_path: Path,
    steps: list[dict[str, Any]],
    succeeds: bool,
    warned: list[str],
    skipped: list[str],
) -> None:
    """The click cases fail or skip after the pick: a step reports the mismatch
    it ran on however it ended. Every row here picks "first" out of 7 matches
    against an expected 1, so the warning content is the same for each name."""
    session = page_session(tmp_path, 7)
    session.driver.click.side_effect = TimeoutError("element not clickable")
    result = run_steps(session, steps, data={"codes": ["a", "b"]})
    assert isinstance(result, FlowSuccess) is succeeds
    assert isinstance(result.warnings[0], AcceptedMatch)
    assert [w.model_dump() for w in result.warnings] == [
        {"step": name, "expected": 1, "found": 7, "picked": "first"} for name in warned
    ]
    assert [s.name for s in result.skipped] == skipped


def test_a_pick_that_matched_the_count_is_silent(tmp_path: Path) -> None:
    result = run_steps(page_session(tmp_path, 1), [read_step(expect=1, pick="first")])
    assert isinstance(result, FlowSuccess)
    assert result.warnings == []


def test_a_failed_run_keeps_the_warnings_of_the_steps_that_ran(tmp_path: Path) -> None:
    result = run_steps(
        page_session(tmp_path, 7),
        [read_step(expect=1, pick="first"), read_step(name="again", expect=1)],
    )
    assert isinstance(result, FlowError)
    assert result.step == "again"
    assert [w.step for w in result.warnings] == ["price"]


def test_the_cli_json_reports_the_warnings(tmp_path: Path) -> None:
    from llm_browser.cli import describe_run

    result = run_steps(page_session(tmp_path, 7), [read_step(expect=1, pick="first")])
    payload = describe_run(result, {}, {})
    assert payload["warnings"] == [
        {"step": "price", "expected": 1, "found": 7, "picked": "first"}
    ]


def test_redaction_keeps_the_warnings(tmp_path: Path) -> None:
    result = run_steps(
        page_session(tmp_path, 7),
        [read_step(expect=1, pick="first")],
        redact=[PRICES[0]],
    )
    assert isinstance(result, FlowSuccess)
    assert [w.found for w in result.warnings] == [7]
    assert result.outputs == {"price": [{"text": "***"}]}
