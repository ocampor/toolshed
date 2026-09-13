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
from llm_browser.scripts import survey_js
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

# A build's numbering on the end of a class name: `card-0-2-3`, `title-17`,
# `css-1x2y3z`. What is left is what the next deploy will still call it.
CLASS_SUFFIX = re.compile(r"(?:-(?:\d+|[A-Za-z0-9]*\d[A-Za-z0-9]*))+$")

# Hrefs that go nowhere a step could follow.
DEAD_HREF_SCHEMES = ("#", "javascript:", "mailto:", "tel:")


def class_stem(token: str) -> str:
    """A class name without the build's numbering on the end."""
    return CLASS_SUFFIX.sub("", token) or token


def landmark_selector(node: SurveyNodeRead) -> tuple[int, str] | None:
    """The sturdiest name the element answers to, with its rank: a test id
    outranks a label, a label an id, an id a role. ``None`` for an element
    that offers none of them.

    Same order as ``explore``'s candidates, minus what CSS cannot say: a role
    selects by role alone, and the accessible name stays in ``text``.
    """
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
    """The named elements, deduped by selector and best first.

    Document order inside a rank: the header's landmarks read before the
    footer's, which is the order an author reads the page in anyway.
    """
    found: dict[str, Landmark] = {}
    ranks: dict[str, int] = {}
    for node in nodes:
        named = landmark_selector(node)
        if named is None:
            continue
        rank, selector = named
        seen = found.get(selector)
        if seen is None:
            found[selector] = Landmark(
                selector=selector, tag=node.tag, text=node.text, count=1
            )
            ranks[selector] = rank
        else:
            seen.count += 1
    ranked = sorted(found.values(), key=lambda mark: ranks[mark.selector])
    return ranked[:max_items]


def link_shape(href: str) -> tuple[str, str] | None:
    """A link's family as ``(shape, selector)``; ``None`` when it has none.

    ``/mission/4821`` and ``/mission/5109`` are one shape, ``/mission/<id>``;
    so are ``item?id=1`` and ``item?id=2``, as ``item?<query>``.
    """
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
    """The link families the page navigates by, the busiest first."""
    shapes = [shape for shape in map(link_shape, hrefs) if shape is not None]
    counts = Counter(shapes)
    return [
        LinkShape(shape=shape, selector=selector, count=count)
        for (shape, selector), count in counts.most_common(max_shapes)
    ]


def repeat_selector(repeat: SurveyRepeatRead) -> str:
    """What to write against every member of the run.

    A class every member carries is the whole selector, preferring one the
    build did not number: `dense` outlives `sc-card-0-2-1`. Failing that the
    run is named by what holds it, which is why the parent's test id is read.
    """
    stable = [
        token
        for token in repeat.shared_classes
        if class_stem(token) == token and not hashed_class(token)
    ]
    named = stable or repeat.shared_classes
    if named:
        return f"{repeat.tag}.{escaped_id(named[0])}"
    parent = repeat.parent
    if parent.testid and parent.testid_attribute:
        return f"[{parent.testid_attribute}={css_quoted(parent.testid)}] > {repeat.tag}"
    if parent.id and not generated_id(parent.id):
        return f"#{escaped_id(parent.id)} > {repeat.tag}"
    return f"{parent.tag} > {repeat.tag}"


def repeats_of(runs: list[SurveyRepeatRead], max_repeats: int) -> list[Repeat]:
    """The repeated structures, the busiest first.

    Two grids of the same card are one card: they answer to the same selector,
    so their counts are the same number — which is the number an author is
    about to write a `read` against.
    """
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
    ranked = sorted(merged.values(), key=lambda run: -run.count)
    return ranked[:max_repeats]


def survey_of(read: SurveyRead, max_items: int) -> Survey:
    """The rules, over what the page handed back — no browser involved."""
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
    )


def survey(
    session: "BrowserSession", max_items: int = constants.SURVEY_MAX_ITEMS
) -> Survey:
    """What the page offers a step, in one read: the first call of a session.

    The named elements to write selectors against, the link families the page
    navigates by, the structures it repeats — the cards, rows and items — and
    how long it had been up when asked. Nothing is clicked and nothing is
    scrolled, so the answer is the page as it stands.

    Where ``explore`` answers "is this selector right", ``survey`` answers the
    question before it: which selectors are there to try.
    """
    read = SurveyRead.model_validate(session.evaluate_document(survey_js()))
    return survey_of(read, max_items)
