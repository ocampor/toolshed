"""``survey``: what a page is made of, in one read and one page of output.

The page hands over raw material — elements that carry a name, every href,
every run of siblings — and these rules turn it into the three lists an author
writes steps from: landmarks, link shapes and repeats. Every list is capped
here, so a page with ten thousand elements answers in the same breath as a
page with ten.
"""

import re
from collections import Counter
from typing import TYPE_CHECKING

from llm_browser import constants
from llm_browser.explore_selectors import (
    css_quoted,
    escaped_id,
    generated_id,
    hashed_class,
    href_prefix,
)
from llm_browser.scripts import count_selectors_js, survey_js
from llm_browser.survey_models import (
    Hydration,
    Landmark,
    LinkShape,
    Repeat,
    Survey,
    SurveyNodeRead,
    SurveyRead,
    SurveyRepeatRead,
)

if TYPE_CHECKING:
    from llm_browser.session import BrowserSession

CLASS_SUFFIX = re.compile(constants.CLASS_SUFFIX_PATTERN)

DEAD_HREF_SCHEMES = ("#", "javascript:", "mailto:", "tel:")


def class_stem(token: str) -> str:
    return CLASS_SUFFIX.sub("", token) or token


def landmark_selector(node: SurveyNodeRead) -> tuple[int, str] | None:
    """Same order as ``explore``'s candidates, minus what CSS cannot say."""
    if node.testid and node.testid_attribute:
        return 0, f"[{node.testid_attribute}={css_quoted(node.testid)}]"
    if node.aria_label:
        return 1, f"[aria-label={css_quoted(node.aria_label)}]"
    if node.id and not generated_id(node.id):
        return 2, f"#{escaped_id(node.id)}"
    if node.role:
        return 3, f"[role={css_quoted(node.role)}]"
    return None


def landmarks_of(nodes: list[SurveyNodeRead], max_items: int) -> list[Landmark]:
    """Document order inside a rank: the order an author reads the page."""
    found: dict[str, Landmark] = {}
    ranks: dict[str, int] = {}
    for node in nodes:
        named = landmark_selector(node)
        if named is None:
            continue
        rank, selector = named
        if selector in found:
            continue
        found[selector] = Landmark(selector=selector, tag=node.tag, text=node.text)
        ranks[selector] = rank
    ranked = sorted(found.values(), key=lambda mark: ranks[mark.selector])
    return ranked[:max_items]


def link_shape(href: str) -> tuple[str, str] | None:
    """``/mission/4821`` and ``/mission/5109`` are one shape, ``/mission/<id>``."""
    if not href or href.startswith(DEAD_HREF_SCHEMES):
        return None
    path = href.split("?")[0].split("#")[0]
    prefix = href_prefix(href)
    if prefix is None:
        stem, mark = path, ""
    elif prefix.endswith("/"):
        stem, mark = prefix, "<id>"
    else:
        stem, mark = prefix, "?<query>" if "?" in href else ""
    if not stem:
        return None
    return f"{stem}{mark}", f"a[href^={css_quoted(stem)}]"


def link_shapes_of(hrefs: list[str], max_shapes: int) -> list[LinkShape]:
    shapes = [shape for shape in map(link_shape, hrefs) if shape is not None]
    counts = Counter(shapes)
    return [
        LinkShape(shape=shape, selector=selector, count=count)
        for (shape, selector), count in counts.most_common(max_shapes)
    ]


def repeat_selector(repeat: SurveyRepeatRead) -> str:
    """Every shared class goes in: one utility class names unrelated components (`div.flex`)."""
    stable = [
        token
        for token in repeat.shared_classes
        if class_stem(token) == token and not hashed_class(token)
    ]
    named = stable or repeat.shared_classes
    if named:
        return repeat.tag + "".join(f".{escaped_id(token)}" for token in named)
    parent = repeat.parent
    if parent.testid and parent.testid_attribute:
        return f"[{parent.testid_attribute}={css_quoted(parent.testid)}] > {repeat.tag}"
    if parent.id and not generated_id(parent.id):
        return f"#{escaped_id(parent.id)} > {repeat.tag}"
    return f"{parent.tag} > {repeat.tag}"


def repeats_of(runs: list[SurveyRepeatRead], max_repeats: int) -> list[Repeat]:
    """Two grids of the same card answer to one selector, so they report once."""
    merged: dict[str, Repeat] = {}
    for run in runs:
        selector = repeat_selector(run)
        seen = merged.get(selector)
        if seen is None:
            merged[selector] = Repeat(
                selector=selector,
                count=run.count,
                nested_controls=run.nested_controls,
            )
        else:
            seen.count += run.count
    return sorted(merged.values(), key=repeat_rank)[:max_repeats]


def repeat_rank(run: Repeat) -> tuple[bool, bool, int]:
    """A run you can click into outranks a bigger one you cannot."""
    return (not run.nested_controls, "." not in run.selector, -run.count)


def survey_of(read: SurveyRead, max_items: int) -> Survey:
    return Survey(
        title=read.title,
        url=read.url,
        hydration=Hydration(
            since_navigation_ms=read.since_navigation_ms,
            ready_state=read.ready_state,
        ),
        landmarks=landmarks_of(read.landmarks, max_items),
        link_shapes=link_shapes_of(read.hrefs, constants.SURVEY_MAX_LINK_SHAPES),
        repeats=repeats_of(read.repeats, constants.SURVEY_MAX_REPEATS),
        truncated=read.truncated,
    )


def with_page_counts(found: Survey, counts: dict[str, int]) -> Survey:
    """Rank and run size say nothing of how many elements the selector finds, which a step is written against."""
    return found.model_copy(
        update={
            "landmarks": [
                mark.model_copy(update={"count": counts.get(mark.selector, mark.count)})
                for mark in found.landmarks
            ],
            "repeats": [
                run.model_copy(update={"count": counts.get(run.selector, run.count)})
                for run in found.repeats
            ],
        }
    )


def page_counts(session: "BrowserSession", found: Survey) -> dict[str, int]:
    """A second call: the selectors only exist once built here."""
    selectors = [mark.selector for mark in found.landmarks]
    selectors += [run.selector for run in found.repeats]
    counted = session.evaluate_document(count_selectors_js(selectors))
    return {str(selector): int(count) for selector, count in counted.items()}


def survey(
    session: "BrowserSession", max_items: int = constants.SURVEY_MAX_ITEMS
) -> Survey:
    """Clicks and scrolls nothing; a second call counts what each named selector matches."""
    read = SurveyRead.model_validate(session.evaluate_document(survey_js()))
    found = survey_of(read, max_items)
    return with_page_counts(found, page_counts(session, found))
