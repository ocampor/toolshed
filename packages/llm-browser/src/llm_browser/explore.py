"""``explore`` and ``explore_many``: what a selector matches, and its verdict.

One selector at a time or a page's worth in one call — both answer with the
same ``ExploreResult``. What makes a sturdier selector lives next door, in
:mod:`llm_browser.explore_selectors`.
"""

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
    """Whether a step with this ``intent`` can be written against the selector.

    A ``read`` is happy with any number of matches — that is what it is for —
    so only the other three call two matches ambiguous.
    """
    if count == 0 or first is None:
        return Verdict.MISSING
    if intent is Intent.READ:
        return Verdict.OK
    if count > 1:
        return Verdict.AMBIGUOUS
    return Verdict.OK if READY[intent](first) else Verdict.NOT_ACTIONABLE


def accepted_counts(intent: Intent, count: int) -> set[int]:
    """What a candidate has to match to be one.

    Every intent but ``read`` is after one element. A ``read`` is after the
    list: a candidate that finds one of thirty rows is not a selector to write
    in its place, whatever else it is.
    """
    return {count} if intent is Intent.READ else {1}


def cut(value: str | None, limit: int) -> str | None:
    """A sampled field, shortened. `None` and `""` stay themselves."""
    return value[:limit] if value else value


def empty_everywhere(
    rows: list[dict[str, str | None]], fields: Collection[str]
) -> list[str]:
    """Fields that no sampled row filled in — missing and blank both count."""
    if not rows:
        return []
    return [name for name in fields if not any(row[name] for row in rows)]


def explore(
    session: "BrowserSession",
    selector: Selector,
    extract: dict[str, ExtractField] | None = None,
    sample: int = constants.EXPLORE_SAMPLE_ROWS,
    timeout_ms: int = constants.DEFAULT_WAIT_TIMEOUT_MS,
    intent: Intent = Intent.READ,
    sample_chars: int = constants.EXPLORE_SAMPLE_CHARS,
) -> ExploreResult:
    """Count and sample what ``selector`` matches.

    Never clicks; scrolls an offscreen match into view so the hit test has
    an answer, which is what the click path does before it clicks.

    For writing a step against a page you have not read yet: how many
    elements the selector really finds, what the first ``sample`` of them
    say under ``extract`` (the row's own text when it is omitted), which
    fields stayed empty, and — in ``first`` — whether a click or a fill
    would actually land. ``verdict`` reads all of that against ``intent``.
    A selector that never arrives is a count of zero, not a
    ``TimeoutError`` — "nothing here" is the answer. Each sampled field is
    cut to ``sample_chars``: reading a row whole is what ``read`` is for.
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
    spec = row_spec(extract or parse_extract_spec(None))
    # Only the sampled elements are read: `sample x (fields + 1)`
    # per-element reads (the +1 is `text_chars`), whatever `count` is.
    elements = [session.driver.nth(locator, i) for i in range(min(sample, count))]
    rows = [
        {
            name: cut(session.driver.read_field(element, field), sample_chars)
            for name, field in spec.items()
        }
        for element in elements
    ]
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
    rows: list[dict[str, str | None]],
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
    """Explore every target in one page call, answers in the order asked.

    What ``explore`` costs once, a page's worth of selectors costs together:
    the count, the sample and the first-match read of every target come back
    from a single evaluation, and the wait is the batch's — it ends when the
    first target appears, so a selector that is simply not on the page is a
    count of zero rather than another full timeout.

    Candidates are still verified from Python, at most
    ``EXPLORE_MAX_CANDIDATES`` counts per target: a proposal is only worth
    offering once something has checked what it matches.

    Selectors are CSS: the page is asked with ``querySelectorAll``, and one it
    cannot parse is a ``ValueError`` naming it rather than a silent zero.
    """
    if not targets:
        return []
    specs = [row_spec(target.extract or parse_extract_spec(None)) for target in targets]
    reads = [
        ExploreManyRead.model_validate(answer)
        for answer in session.evaluate_document(
            explore_many_js(
                [
                    {"selector": target.selector, "extract": dict(spec)}
                    for target, spec in zip(targets, specs)
                ],
                sample,
                sample_chars,
                timeout_ms,
            )
        )
    ]
    refused = [read.selector for read in reads if read.invalid]
    if refused:
        raise ValueError(f"Not CSS the page can parse: {', '.join(refused)}")
    return [
        explore_result(
            session,
            read=read.element,
            count=read.count,
            rows=read.sample,
            spec=spec,
            text_chars=read.text_chars,
            intent=target.intent,
            stability=selector_stability(target.selector),
            since_call_ms=read.since_call_ms,
        )
        for target, spec, read in zip(targets, specs, reads)
    ]


def first_match(session: "BrowserSession", locator: Any) -> ExploreRead:
    """The first match as a click would find it, what it offers a selector,
    and how long the page had been up — one page evaluation for all three."""
    raw = session.driver.evaluate(session.driver.first(locator), explore_first_js())
    return ExploreRead.model_validate(raw)


def verified_candidates(
    session: "BrowserSession", proposals: list[str], accepted: Collection[int]
) -> list[str]:
    """The proposals whose own count is one ``accepted`` here.

    Only the best ``EXPLORE_MAX_CANDIDATES`` proposals are checked — one
    count each, so ``explore`` costs a bounded number of round trips
    however many things the element could be called.

    A unique match *is* the first match: every proposal was built from
    something read off it (or off the row carrying it).
    """
    checked = proposals[: constants.EXPLORE_MAX_CANDIDATES]
    return [
        candidate for candidate in checked if session.count_of(candidate) in accepted
    ]
