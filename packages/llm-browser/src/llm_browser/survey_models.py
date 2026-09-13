"""What ``survey`` reads off a page, and what it answers with.

Two layers: the ``Survey*Read`` models are the page's raw material — every
element that carries a name, every href, every run of siblings — and the rest
is what :mod:`llm_browser.survey` makes of it.
"""

from pydantic import BaseModel, Field

from llm_browser.explore_models import NestedControl


class SurveyNodeRead(BaseModel):
    """An element the page offered a name for, before any ranking."""

    tag: str
    testid_attribute: str | None = None
    testid: str | None = None
    aria_label: str | None = None
    id: str | None = None
    role: str | None = None
    text: str = ""


class SurveyParentRead(BaseModel):
    """The element a run of siblings sits in, as far as naming it goes."""

    tag: str
    testid_attribute: str | None = None
    testid: str | None = None
    id: str | None = None


class SurveyRepeatRead(BaseModel):
    """A run of same-tag siblings: the cards, rows and list items of a page.

    ``shared_classes`` are the classes every member carries — the ones a
    selector can be written against; ``classes`` are the first member's, hashed
    ones included.
    """

    tag: str
    count: int
    classes: list[str] = Field(default_factory=list)
    shared_classes: list[str] = Field(default_factory=list)
    parent: SurveyParentRead
    nested_controls: list[NestedControl] = Field(default_factory=list)


class SurveyRead(BaseModel):
    """What one page evaluation of ``js/survey.js`` answers."""

    title: str = ""
    url: str = ""
    ready_state: str = ""
    since_navigation_ms: int = 0
    landmarks: list[SurveyNodeRead] = Field(default_factory=list)
    hrefs: list[str] = Field(default_factory=list)
    repeats: list[SurveyRepeatRead] = Field(default_factory=list)
    truncated: bool = False


class Landmark(BaseModel):
    """An element with a name worth writing a selector against.

    ``count`` is how many elements on the page answer to ``selector`` — one
    means the selector is already a step's worth on its own. ``tag`` and
    ``text`` are the first element reported under the name, whatever the count.
    """

    selector: str
    tag: str
    text: str = ""
    count: int = 1


class LinkShape(BaseModel):
    """A family of links that differ only in the page they point at."""

    shape: str
    selector: str
    count: int


class Repeat(BaseModel):
    """A structure the page uses more than twice — a card, a row, an item.

    ``count`` is how many elements ``selector`` matches page-wide — the number
    a ``read`` against it is about to return, not the size of the run it was
    found in. ``nested_controls`` are the controls inside one of them: what a
    click on the whole thing would land on instead.
    """

    selector: str
    count: int
    nested_controls: list[NestedControl] = Field(default_factory=list)


class Hydration(BaseModel):
    """How far along the page was when it was surveyed.

    ``since_navigation_ms`` is the number a ``wait_for`` timeout should be
    sized from; ``ready_state`` says whether anything is still arriving.
    """

    since_navigation_ms: int
    ready_state: str


class Survey(BaseModel):
    """What a page is made of, before any selector has been written.

    No clicks and no scrolling: the named elements to write steps against, the
    link families the page navigates by, the structures it repeats, and how
    long it had been up.

    ``truncated`` is true when a raw cap cut the page short — the lists are a
    sample of it rather than all of it, and a narrower page (or a frame) is
    the way to see the rest.
    """

    title: str
    url: str
    hydration: Hydration
    landmarks: list[Landmark] = Field(default_factory=list)
    link_shapes: list[LinkShape] = Field(default_factory=list)
    repeats: list[Repeat] = Field(default_factory=list)
    truncated: bool = False
