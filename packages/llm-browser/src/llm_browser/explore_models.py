"""What ``explore`` reports: the first match, its locators, and the verdict."""

import enum

from pydantic import BaseModel, computed_field, Field

from llm_browser.constants import EXPLORE_NON_BLOCKING


class Intent(enum.StrEnum):
    """What the step being written will do with the selector."""

    READ = "read"
    CLICK = "click"
    FILL = "fill"
    WAIT = "wait"


class Verdict(enum.StrEnum):
    """Whether the selector is fit for the intent, in one word."""

    OK = "ok"
    AMBIGUOUS = "ambiguous"
    MISSING = "missing"
    NOT_ACTIONABLE = "not_actionable"


class Stability(enum.StrEnum):
    """How much of the selector a redeploy is likely to take with it."""

    DATA_TESTID = "data-testid"
    ARIA = "aria"
    ID = "id"
    CLASS_HASH = "class-hash"
    POSITIONAL = "positional"
    OTHER = "other"


class Covering(BaseModel):
    """The element sitting over the first match's centre."""

    tag: str
    text: str


class NestedControl(BaseModel):
    """A control inside the first match, which a loose click lands on instead."""

    tag: str
    text: str


class Locators(BaseModel):
    """What the first match offers a selector, before any rule is applied.

    The page reports; :mod:`llm_browser.explore` decides which of these make a
    candidate and in what order.
    """

    tag: str
    testid_attribute: str | None = None
    testid: str | None = None
    testid_depth: int = 0
    aria_label: str | None = None
    role: str | None = None
    name: str | None = None
    id: str | None = None
    href: str | None = None
    classes: list[str] = Field(default_factory=list)


class FirstMatch(BaseModel):
    """The first match as a click would find it.

    Each name in ``why_not`` is one reason a click would miss — see
    ``docs/API.md`` for the list. ``hit_tested`` is false when the centre was
    not a point the page could be asked about, so ``covered_by`` of ``None``
    means "not asked" rather than "nothing over it".
    """

    tag: str
    text: str
    role: str | None = None
    aria_label: str | None = None
    name: str | None = None
    href: str | None = None
    visible: bool
    enabled: bool
    in_viewport: bool
    covered_by: Covering | None = None
    hit_tested: bool = True
    stable: bool
    pointer_events: bool
    why_not: list[str] = Field(default_factory=list)
    nested_controls: list[NestedControl] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def clickable(self) -> bool:
        """Nothing in ``why_not`` a driver does not handle itself: every one
        of them scrolls the target into view before clicking, so ``offscreen``
        is information rather than an obstacle."""
        return not [
            reason for reason in self.why_not if reason not in EXPLORE_NON_BLOCKING
        ]


class ExploreRead(BaseModel):
    """What one page evaluation of the first match answers."""

    first: FirstMatch
    locators: Locators
    since_navigation_ms: int


class ExploreResult(BaseModel):
    """What a selector matches right now, for an author sizing up a step.

    ``empty_fields`` names the fields no sampled row filled in — a wrong
    child selector, or a page that has not hydrated yet — and ``text_chars``
    is how much rendered text the sampled elements carry between them.
    ``verdict`` answers the intent; ``candidates`` are sturdier selectors that
    were checked to match the same element and nothing else.
    ``since_navigation_ms`` is how long the page had been up when the first
    match was read — the one a `wait_for` timeout should be sized from, since
    ``since_call_ms`` only counts from a call that may follow the load by
    seconds.
    """

    count: int
    sample: list[dict[str, str | None]]
    empty_fields: list[str]
    text_chars: int
    first: FirstMatch | None = None
    since_navigation_ms: int | None = None
    since_call_ms: int | None = None
    candidates: list[str] = Field(default_factory=list)
    stability: Stability = Stability.OTHER
    verdict: Verdict = Verdict.MISSING
