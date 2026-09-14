"""What a survey makes of a page: landmarks, link shapes, repeats, caps.

The rules are exercised over real markup. ``read_html`` is the collecting half
of ``js/survey.js`` in Python — the same three lists, off an lxml tree instead
of a live DOM — and ``page_counts_of`` stands in for the counting call, with
lxml's own CSS engine answering the selectors the rules named. So the ranking,
the grouping and the counts can be tested without a browser; the scripts
themselves are covered by the `survey a page` conformance scenario.
"""

from itertools import product
from string import ascii_lowercase

from lxml import html as lxml_html

from llm_browser import constants
from llm_browser.explore_models import NestedControl
from llm_browser.survey import class_stem, survey_of, with_page_counts
from llm_browser.survey_models import (
    SurveyNodeRead,
    SurveyParentRead,
    SurveyRead,
    SurveyRepeatRead,
)

PAGE = """
<html><head><title>Missions</title></head>
<body>
  <header id="masthead" data-testing-id="top">
    <input id="search" aria-label="Search missions">
    <nav role="navigation"><a href="/about">About</a></nav>
  </header>
  <main id="grid">
    <article class="sc-card-0-2-1 dense"><a href="/mission/4821">Senior engineer</a>
      <button>Save</button></article>
    <article class="sc-card-0-2-1 dense"><a href="/mission/5109">Staff engineer</a>
      <button>Save</button></article>
    <article class="sc-card-0-2-1 dense"><a href="/mission/6710">Principal</a>
      <button>Save</button></article>
  </main>
  <aside id="react-select-2-input">
    <article class="sc-card-0-2-9 dense"><a href="/mission/77">Nearby</a></article>
    <article class="sc-card-0-2-9 dense"><a href="/mission/78">Nearby</a></article>
    <article class="sc-card-0-2-9 dense"><a href="/mission/79">Nearby</a></article>
  </aside>
  <footer><a href="mailto:hi@example.com">Mail</a><a href="#top">Top</a></footer>
</body></html>
"""


def read_html(tree: object, truncated: bool = False) -> SurveyRead:
    return SurveyRead(
        title="Missions",
        url="https://example.com/missions",
        ready_state="complete",
        since_navigation_ms=1200,
        landmarks=[node for node in map(landmark_of, tree.iter()) if node is not None],
        hrefs=[anchor.get("href") for anchor in tree.iter("a")],
        repeats=[run for parent in tree.iter() for run in runs_of(parent)],
        truncated=truncated,
    )


def landmark_of(element: object) -> SurveyNodeRead | None:
    if not isinstance(element.tag, str):
        return None
    attribute, value = marker_of(element)
    named = (value, element.get("aria-label"), element.get("id"), element.get("role"))
    if not any(named):
        return None
    return SurveyNodeRead(
        tag=element.tag,
        testid_attribute=attribute,
        testid=value,
        aria_label=element.get("aria-label"),
        id=element.get("id"),
        role=element.get("role"),
        text=" ".join(element.text_content().split())[
            : constants.SURVEY_TEXT_MAX_CHARS
        ],
    )


def marker_of(element: object) -> tuple[str | None, str | None]:
    for attribute in constants.TESTID_ATTRIBUTES:
        if element.get(attribute):
            return attribute, element.get(attribute)
    return None, None


def runs_of(parent: object) -> list[SurveyRepeatRead]:
    children = [child for child in parent if isinstance(child.tag, str)]
    if len(children) < constants.SURVEY_MIN_SIBLINGS:
        return []
    kinds: dict[str, list[object]] = {}
    for child in children:
        stems = sorted(class_stem(token) for token in child.classes)
        kinds.setdefault(f"{child.tag}|{' '.join(stems)}", []).append(child)
    runs = []
    for members in kinds.values():
        if len(members) < constants.SURVEY_MIN_SIBLINGS:
            continue
        classes = [list(member.classes) for member in members]
        runs.append(
            SurveyRepeatRead(
                tag=members[0].tag,
                count=len(members),
                classes=classes[0],
                shared_classes=[
                    token
                    for token in classes[0]
                    if all(token in other for other in classes)
                ],
                parent=SurveyParentRead(
                    tag=parent.tag,
                    testid_attribute=marker_of(parent)[0],
                    testid=marker_of(parent)[1],
                    id=parent.get("id"),
                ),
                nested_controls=controls_of(members[0]),
            )
        )
    return runs


def controls_of(member: object) -> list[NestedControl]:
    found = member.xpath(".//button | .//a | .//input")
    return [
        NestedControl(
            tag=control.tag,
            text=" ".join(control.text_content().split())[
                : constants.EXPLORE_NESTED_TEXT_MAX_CHARS
            ],
        )
        for control in found[: constants.EXPLORE_MAX_NESTED_CONTROLS]
    ]


def survey_page(source: str = PAGE, max_items: int = 60) -> object:
    """The two calls a real survey makes, over one tree: the read, then the
    count of every selector the rules named."""
    tree = lxml_html.fromstring(source)
    found = survey_of(read_html(tree), max_items)
    return with_page_counts(found, page_counts_of(tree, found))


def page_counts_of(tree: object, found: object) -> dict[str, int]:
    selectors = [mark.selector for mark in found.landmarks]
    selectors += [run.selector for run in found.repeats]
    return {selector: len(tree.cssselect(selector)) for selector in selectors}


def test_landmarks_lead_with_what_survives_a_redeploy() -> None:
    """A test id first, then a label, then an id, then a bare role — and a
    generated id is no name at all."""
    found = survey_page()

    # One name each: the header answers to its test id, not also to its id.
    assert [mark.selector for mark in found.landmarks] == [
        '[data-testing-id="top"]',
        '[aria-label="Search missions"]',
        "#grid",
        '[role="navigation"]',
    ]
    assert found.landmarks[0].tag == "header"
    # `react-select-2-input` is this render's numbering, not the element's name.
    assert not [mark for mark in found.landmarks if "react-select" in mark.selector]


def test_links_are_grouped_by_the_section_they_point_at() -> None:
    """Forty missions are one shape and one selector, not forty hrefs."""
    found = survey_page()

    assert found.link_shapes[0].shape == "/mission/<id>"
    assert found.link_shapes[0].selector == 'a[href^="/mission/"]'
    assert found.link_shapes[0].count == 6
    assert [shape.shape for shape in found.link_shapes[1:]] == ["/about"]


def test_the_cards_are_one_repeat_however_the_build_numbered_them() -> None:
    """`sc-card-0-2-1` and `sc-card-0-2-9` are the same card twice: the stem
    is what the next deploy will still call it."""
    found = survey_page()

    assert [(run.selector, run.count) for run in found.repeats] == [
        ("article.dense", 6)
    ]


def test_a_card_with_no_stable_class_is_named_by_what_holds_it() -> None:
    page = """
    <main data-testid="results">
      <div class="x-1"></div><div class="x-2"></div><div class="x-3"></div>
    </main>
    """
    found = survey_page(page)

    assert found.repeats[0].selector == '[data-testid="results"] > div'


def test_hydration_is_the_number_a_wait_is_sized_from() -> None:
    found = survey_page()

    assert found.hydration.since_navigation_ms == 1200
    assert found.hydration.ready_state == "complete"
    assert found.title == "Missions"


def test_every_list_is_capped_so_the_answer_stays_one_page() -> None:
    """A page of ten thousand named elements answers in the same breath."""
    ids = ["".join(letters) for letters in product(ascii_lowercase[:6], repeat=3)]
    crowd = "".join(f'<p id="{name}">text</p>' for name in ids)
    links = "".join(
        f'<a href="/post/{index}/x{index}">post</a>' for index in range(200)
    )
    found = survey_page(f"<html><body>{crowd}{links}</body></html>")

    assert len(found.landmarks) == 60
    assert len(found.link_shapes) <= constants.SURVEY_MAX_LINK_SHAPES
    assert len(found.repeats) <= constants.SURVEY_MAX_REPEATS
    assert len(found.model_dump_json()) < 8_000


def test_a_class_stem_drops_the_build_numbering_only() -> None:
    assert class_stem("sc-card-0-2-1") == "sc-card"
    assert class_stem("css-1x2y3z") == "css"
    assert class_stem("mission-card") == "mission-card"


def test_a_table_of_rows_is_its_story_rows_not_its_spacers() -> None:
    """Grouping by tag alone reads a news table as ninety `tr`; the rows an
    author is after are the ones that share a class."""
    rows = "".join(
        '<tr class="athing"><td>story</td></tr><tr class="spacer"></tr><tr></tr>'
        for _ in range(4)
    )
    found = survey_page(f"<table><tbody>{rows}</tbody></table>")

    # The classless run reads last: it is the table's own rows, not the ones
    # an author came for.
    # `tbody > tr` is the whole table, twelve rows: the count is what the
    # selector returns, not the size of the run it was spotted in.
    assert [(run.selector, run.count) for run in found.repeats] == [
        ("tr.athing", 4),
        ("tr.spacer", 4),
        ("tbody > tr", 12),
    ]


def test_a_run_you_can_click_into_outranks_a_bigger_one_you_cannot() -> None:
    """A page's cards are what an author came for; the fifty spans of its code
    sample are not, however many of them there are."""
    spans = "".join('<span class="tok">x</span>' for _ in range(50))
    cards = "".join('<div class="card"><a href="/c">Open</a></div>' for _ in range(3))
    found = survey_page(f"<body><pre>{spans}</pre><main>{cards}</main></body>")

    assert [(run.selector, run.count) for run in found.repeats] == [
        ("div.card", 3),
        ("span.tok", 50),
    ]
    assert [c.text for c in found.repeats[0].nested_controls] == ["Open"]


def test_one_utility_class_does_not_make_two_components_one_repeat() -> None:
    """`div.flex` is three cards and four footer rows; the selector has to say
    which of them it means, so every shared class goes into it."""
    cards = "".join('<div class="flex p-4 rounded">card</div>' for _ in range(3))
    chrome = "".join('<div class="flex gap-2 border">bit</div>' for _ in range(4))
    found = survey_page(
        f"<body><section>{cards}</section><footer>{chrome}</footer></body>"
    )

    # `p-4` and `gap-2` read as the build's numbering and drop out; what is
    # left still tells the two runs apart, which is the whole point.
    assert sorted((run.selector, run.count) for run in found.repeats) == [
        ("div.flex.border", 4),
        ("div.flex.rounded", 3),
    ]


def test_a_landmark_counts_every_element_that_answers_to_it() -> None:
    """The rank picks which name a landmark is reported under; it says nothing
    about how many elements answer to that name — and a `1` that is really a
    `2` is the `ambiguous` a survey exists to catch before the run."""
    page = """
    <body>
      <a aria-label="Next" href="/2">next</a>
      <button data-testid="next-btn" aria-label="Next">Next</button>
    </body>
    """
    found = survey_page(page)

    counts = {mark.selector: mark.count for mark in found.landmarks}
    assert counts == {'[data-testid="next-btn"]': 1, '[aria-label="Next"]': 2}


def test_a_page_that_outgrew_the_caps_says_so() -> None:
    """ "You got the top N" and "whole sections are missing" are different
    answers, and only one of them is worth trusting."""
    tree = lxml_html.fromstring(PAGE)

    assert not survey_of(read_html(tree), 60).truncated
    assert survey_of(read_html(tree, truncated=True), 60).truncated
