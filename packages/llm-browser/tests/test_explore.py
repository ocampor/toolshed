"""The selector rules behind `explore`: what to propose, and what it costs."""

import pytest

from llm_browser.explore import (
    accepted_counts,
    candidate_selectors,
    css_quoted,
    generated_id,
    href_prefix,
)
from llm_browser.explore_models import Intent, Locators


def locators(**fields: object) -> Locators:
    return Locators.model_validate({"tag": "a", **fields})


def test_candidates_are_ranked_by_what_survives_a_redeploy() -> None:
    """A test id outlives a redesign, an aria label a restyle, an id both —
    a link's section outlives the page, and a hashed class outlives nothing."""
    proposed = candidate_selectors(
        locators(
            testid_attribute="data-testid",
            testid="mission-card",
            aria_label="Open mission",
            role="link",
            name="Open mission",
            id="mission",
            href="/missions/senior-eng-4821",
            classes=["card", "css-1x2y3z"],
        ),
        role_selectors=True,
    )

    assert proposed == [
        '[data-testid="mission-card"]',
        '[aria-label="Open mission"]',
        'role=link[name="Open mission"]',
        "#mission",
        'a[href^="/missions/"]',
        ".css-1x2y3z",
    ]


def test_a_test_id_on_an_ancestor_scopes_down_to_the_match() -> None:
    """The id names the row; the match is what is inside it, so the candidate
    has to descend — and `:is()` keeps the tail from adding specificity."""
    proposed = candidate_selectors(
        locators(testid_attribute="data-testing-id", testid="row", testid_depth=2),
        role_selectors=True,
    )

    assert proposed == ['[data-testing-id="row"] :is(a)']


def test_a_test_id_on_the_match_itself_needs_no_scope() -> None:
    proposed = candidate_selectors(
        locators(testid_attribute="data-testid", testid="row", testid_depth=0),
        role_selectors=True,
    )

    assert proposed == ['[data-testid="row"]']


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("plain", '"plain"'),
        # Unescaped, the quote ends the string and the rest is a syntax error
        # or, worse, a selector for something else.
        ('say "hi"', '"say \\"hi\\""'),
        ("back\\slash", '"back\\\\slash"'),
        ("two\nlines", '"two\\a lines"'),
    ],
)
def test_an_attribute_value_is_escaped_as_a_css_string(
    value: str, expected: str
) -> None:
    assert css_quoted(value) == expected


def test_only_the_best_hashed_class_is_proposed() -> None:
    """A utility-class element carries eight of them; verifying each costs a
    round trip and none of them outlives the next redeploy anyway."""
    proposed = candidate_selectors(
        locators(classes=["css-1x2y3z", "css-9a8b7c", "w-[42px]"]),
        role_selectors=True,
    )

    assert proposed == [".css-1x2y3z"]


def test_a_class_is_escaped_before_it_becomes_a_selector() -> None:
    """`.w-[42px]` unescaped is a syntax error, not a candidate."""
    proposed = candidate_selectors(locators(classes=["w-[42px]"]), role_selectors=True)

    assert proposed == [r".w-\[42px\]"]


def test_a_driver_that_cannot_parse_role_is_not_offered_one() -> None:
    """`role=` is Playwright's own syntax; elsewhere it is a syntax error in
    the flow the author writes next."""
    offers = locators(role="link", name="Open mission", id="mission")

    assert candidate_selectors(offers, role_selectors=False) == ["#mission"]


def test_a_generated_id_is_not_proposed() -> None:
    assert (
        candidate_selectors(locators(id="react-select-2-input"), role_selectors=True)
        == []
    )


@pytest.mark.parametrize(
    ("value", "generated"),
    [
        ("searchInput", False),
        ("mw-content-text", False),
        ("react-select-2-input", True),
        ("46150879", True),
        ("a" * 41, True),
    ],
)
def test_which_ids_read_as_generated(value: str, generated: bool) -> None:
    assert generated_id(value) is generated


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        # The page is the number; the section is what is left.
        ("/missions/senior-eng-4821", "/missions/"),
        ("/item?id=46150879", "/item"),
        # Nothing to generalize: the prefix would be the link itself.
        ("/learn/thinking-in-react", None),
        ("https://iana.org/domains/example", None),
        # The query is the page; the path is the section.
        ("login?goto=news", "login"),
        ("?p=2", None),
        ("/", None),
        ("", None),
        ("/2026/", None),
    ],
)
def test_the_href_prefix_is_the_section_not_the_page(
    href: str, expected: str | None
) -> None:
    assert href_prefix(href) == expected


def test_a_read_wants_a_candidate_that_matches_every_row() -> None:
    """`.card` finding all 30 rows is the selector to write for a `read`; one
    that finds a single row is not a replacement for the list."""
    assert accepted_counts(Intent.READ, 30) == {30}
    assert accepted_counts(Intent.READ, 1) == {1}
    assert accepted_counts(Intent.CLICK, 30) == {1}
