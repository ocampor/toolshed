import time
from collections.abc import Callable, Collection
from typing import TYPE_CHECKING, Any

from llm_browser import constants
from llm_browser.explore_models import (
    ExploreManyRead,
    ExploreRead,
    ExploreResult,
    ExploreTarget,
    FirstMatch,
    Intent,
    Stability,
    Verdict,
)
from llm_browser.explore_selectors import candidate_selectors, selector_stability
from llm_browser.extract_values import Row, is_typed, preview_rows
from llm_browser.parse import ExtractField, parse_extract_spec, row_spec
from llm_browser.scripts import explore_first_js, explore_many_js
from llm_browser.selectors import Selector, describe_selector

if TYPE_CHECKING:
    from llm_browser.session import BrowserSession

# Every intent but ``read`` wants exactly one match; these say what else it
# wants of that match.
READY: dict[Intent, Callable[[FirstMatch], bool]] = {
    Intent.READ: lambda first: True,
    Intent.WAIT: lambda first: True,
    Intent.CLICK: lambda first: first.clickable,
    Intent.FILL: lambda first: first.visible and first.enabled,
}


def verdict_for(intent: Intent, count: int, first: FirstMatch | None) -> Verdict:
    """A ``read`` takes any number of matches; only the other intents call two ambiguous."""
    if count == 0 or first is None:
        return Verdict.MISSING
    if intent is Intent.READ:
        return Verdict.OK
    if count > 1:
        return Verdict.AMBIGUOUS
    return Verdict.OK if READY[intent](first) else Verdict.NOT_ACTIONABLE


def accepted_counts(intent: Intent, count: int) -> set[int]:
    """A ``read`` wants the list: a candidate finding one of thirty rows is not its replacement."""
    return {count} if intent is Intent.READ else {1}


def empty_everywhere(rows: list[Row], fields: Collection[str]) -> list[str]:
    if not rows:
        return []
    return [name for name in fields if all(row[name] in (None, "") for row in rows)]


def explore_spec(extract: dict[str, ExtractField]) -> dict[str, dict[str, Any]]:
    """``row_spec``; a typed field is read ``whole`` and cut after typing."""
    spec = row_spec(extract)
    return {
        name: {**spec[name], "whole": True} if is_typed(extract[name]) else spec[name]
        for name in spec
    }


def explore(
    session: "BrowserSession",
    selector: Selector,
    extract: dict[str, ExtractField] | None = None,
    sample: int = constants.EXPLORE_SAMPLE_ROWS,
    timeout_ms: int = constants.DEFAULT_WAIT_TIMEOUT_MS,
    intent: Intent = Intent.READ,
    sample_chars: int = constants.EXPLORE_SAMPLE_CHARS,
) -> ExploreResult:
    """Never clicks, but scrolls an offscreen match into view so the hit test can answer.
    A selector that never arrives is a count of zero, not a ``TimeoutError``.
    """
    stability = selector_stability(describe_selector(selector))
    started = time.monotonic()
    try:
        locator = session.find_all(selector, timeout=timeout_ms)
    except TimeoutError:
        return ExploreResult(
            count=0, sample=[], empty_fields=[], text_chars=0, stability=stability
        )
    since_call_ms = round((time.monotonic() - started) * 1000)
    count = session.driver.count(locator)
    fields = extract or parse_extract_spec(None)
    spec = row_spec(fields)
    # Only the sampled elements are read: `sample x (fields + 1)`
    # per-element reads (the +1 is `text_chars`), whatever `count` is.
    elements = [session.driver.nth(locator, i) for i in range(min(sample, count))]
    read_field = session.driver.read_field
    raw = [
        {name: read_field(el, field) for name, field in spec.items()} for el in elements
    ]
    rows = preview_rows(raw, fields, sample_chars)
    return explore_result(
        session,
        read=session.first_match(locator) if count else None,
        count=count,
        rows=rows,
        spec=spec,
        text_chars=sum(
            len(session.driver.read_property(el, "innerText") or "") for el in elements
        ),
        intent=intent,
        stability=stability,
        since_call_ms=since_call_ms,
    )


def explore_result(
    session: "BrowserSession",
    *,
    read: ExploreRead | None,
    count: int,
    rows: list[Row],
    spec: Collection[str],
    text_chars: int,
    intent: Intent,
    stability: Stability,
    since_call_ms: int,
) -> ExploreResult:
    """One selector's answer, however it was read: the rules that turn a first
    match into a verdict and a list of candidates belong to one function."""
    first = read.first if read else None
    return ExploreResult(
        count=count,
        sample=rows,
        empty_fields=empty_everywhere(rows, spec),
        text_chars=text_chars,
        first=first,
        since_navigation_ms=read.since_navigation_ms if read else None,
        since_call_ms=since_call_ms,
        candidates=session.verified_candidates(
            candidate_selectors(
                read.locators,
                role_selectors=session.driver.supports_role_selector,
            )
            if read
            else [],
            accepted_counts(intent, count),
        ),
        stability=stability,
        verdict=verdict_for(intent, count, first),
    )


def explore_many(
    session: "BrowserSession",
    targets: list[ExploreTarget],
    sample: int = constants.EXPLORE_SAMPLE_ROWS,
    sample_chars: int = constants.EXPLORE_SAMPLE_CHARS,
    timeout_ms: int = constants.DEFAULT_WAIT_TIMEOUT_MS,
) -> list[ExploreResult]:
    """One page call; the wait ends when the first target appears, so a missing one costs no extra timeout.
    An unparseable selector gets its own answer; the call costs ``timeout_ms`` plus 100 ms per target.
    """
    if not targets:
        return []
    if len(targets) > constants.EXPLORE_MANY_MAX_TARGETS:
        raise ValueError(
            f"explore_many takes at most {constants.EXPLORE_MANY_MAX_TARGETS} "
            f"targets in one call, got {len(targets)}"
        )
    extracts = [target.extract or parse_extract_spec(None) for target in targets]
    reads = [
        ExploreManyRead.model_validate(answer)
        for answer in session.evaluate_document(
            explore_many_js(
                [
                    {"selector": target.selector, "extract": explore_spec(extract)}
                    for target, extract in zip(targets, extracts)
                ],
                sample,
                sample_chars,
                timeout_ms,
            ),
            timeout_ms=batch_evaluate_timeout_ms(timeout_ms, len(targets)),
        )
    ]
    return [
        refused_result(target)
        if read.invalid
        else explore_result(
            session,
            read=read.element,
            count=read.count,
            rows=preview_rows(read.sample, extract, sample_chars),
            spec=extract,
            text_chars=read.text_chars,
            intent=target.intent,
            stability=selector_stability(target.selector),
            since_call_ms=read.since_call_ms,
        )
        for target, extract, read in zip(targets, extracts, reads)
    ]


def batch_evaluate_timeout_ms(timeout_ms: int, targets: int) -> int:
    """Or the driver's own default timeout ends the call before the caller's wait does."""
    settles = targets * constants.EXPLORE_STABLE_DELAY_MS
    return timeout_ms + settles + constants.EXPLORE_MANY_MARGIN_MS


def refused_result(target: ExploreTarget) -> ExploreResult:
    """One target's typo is its own answer; the batch already paid for the others."""
    return ExploreResult(
        count=0,
        sample=[],
        empty_fields=[],
        text_chars=0,
        stability=selector_stability(target.selector),
        verdict=Verdict.MISSING,
        error="not css",
    )


def first_match(session: "BrowserSession", locator: Any) -> ExploreRead:
    """The first match as a click would find it, what it offers a selector,
    and how long the page had been up — one page evaluation for all three."""
    raw = session.driver.evaluate(session.driver.first(locator), explore_first_js())
    return ExploreRead.model_validate(raw)


def verified_candidates(
    session: "BrowserSession", proposals: list[str], accepted: Collection[int]
) -> list[str]:
    """Only the best ``EXPLORE_MAX_CANDIDATES`` are counted, bounding round trips."""
    checked = proposals[: constants.EXPLORE_MAX_CANDIDATES]
    return [
        candidate for candidate in checked if session.count_of(candidate) in accepted
    ]
