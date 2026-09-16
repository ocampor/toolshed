"""The humanized click against a real Chromium: does the hit test the click
trusts — run in patchright's isolated world — see what the page itself sees?

The fakes elsewhere can only prove the plumbing. Isolated-world
``elementFromPoint`` reading a different element than the main world's would
make every refusal and every reported hit a lie, and nothing but a browser
can answer that.
"""

import random
from pathlib import Path
from typing import Any, Iterator, NamedTuple

import pytest

from llm_browser import session_input
from llm_browser.behavior import Behavior
from llm_browser.session import BrowserSession

# A fixed nav whose hover menu drops over the page, and a logout link the
# wheel has to bring in: the shape the hit test was written for. The nav's
# edge and the link's place vary, because a wheel that parks the target flush
# against a viewport edge lands it under exactly such a nav.
PAGE = """
<style>
  body {{ margin: 0; height: 3000px; font: 16px sans-serif; }}
  nav {{ position: fixed; {nav_edge}: 0; left: 0; right: 0; height: {nav_height}px;
        z-index: 10; background: #223344; color: #fff; padding: 18px; }}
  nav .menu {{ display: none; position: absolute; top: {nav_height}px; left: 0;
              right: 0; height: 200px; margin: 0; padding: 0;
              background: #cceeff; }}
  nav:hover .menu {{ display: block; }}
  nav .menu li {{ list-style: none; padding: 24px; }}
  a.logout {{ position: absolute; top: {link_top}px; left: 120px;
             padding: 14px 22px; background: #eeeeee; }}
</style>
<nav>Cuenta
  <ul class="menu"><li class="menu-item">Estados de cuenta</li></ul>
</nav>
<a class="logout" id="logout" href="#gone"><span class="label">Salir</span></a>
"""


class Case(NamedTuple):
    """A page and where it starts scrolled, plus whether the click must land.

    ``must_click`` is off only for the original shape, where the path crosses
    the nav on its way down and the menu legitimately takes the point.
    """

    nav_edge: str
    nav_height: int
    link_top: int
    start_at: int
    must_click: bool

    def html(self) -> str:
        return PAGE.format(
            nav_edge=self.nav_edge, nav_height=self.nav_height, link_top=self.link_top
        )


CASES = {
    "below the fold, nav on top": Case("top", 60, 2400, 0, must_click=False),
    # Wheeling up: the minimal scroll stops with the box flush against the top
    # edge, which is where the fixed nav is.
    "above the fold, nav on top": Case("top", 60, 800, 1200, must_click=True),
    # Wheeling down: the minimal scroll stops with the box flush against the
    # bottom edge, which is where this nav is.
    "below the fold, nav on the bottom": Case("bottom", 80, 2400, 0, must_click=True),
}


@pytest.fixture
def live_session(tmp_path: Path) -> Iterator[BrowserSession]:
    session = BrowserSession(
        state_dir=tmp_path, driver="patchright", behavior=Behavior.human()
    )
    try:
        session.launch(headed=False)
    except Exception as exc:
        pytest.skip(f"patchright chromium would not launch: {exc}")
    try:
        yield session
    finally:
        session.close()


def main_world_at(cdp: Any, point: tuple[float, float]) -> str:
    """``tag|class`` of whatever the *page's own* world finds at ``point``.

    ``Runtime.evaluate`` with no context id is the main world; patchright's
    ``evaluate`` deliberately is not, which is the whole question here.
    """
    read = cdp.send(
        "Runtime.evaluate",
        {
            "expression": (
                f"(() => {{ const at = document.elementFromPoint{point};"
                " return at ? at.tagName.toLowerCase() + '|' + at.className"
                " : 'nothing'; })()"
            ),
            "returnByValue": True,
        },
    )
    return str(read["result"]["value"])


@pytest.mark.parametrize("case", CASES.values(), ids=list(CASES))
def test_hit_test_agrees_with_the_main_world_in_patchright(
    live_session: BrowserSession, monkeypatch: pytest.MonkeyPatch, case: Case
) -> None:
    random.seed(20260916)
    page = live_session.get_page()
    page.set_content(case.html())
    page.evaluate(f"() => window.scrollTo(0, {case.start_at})")
    cdp = page.context.new_cdp_session(page)
    jumped: list[Any] = []
    monkeypatch.setattr(
        type(live_session.driver),
        "scroll_into_view",
        lambda self, el: jumped.append(el),
    )

    seen: list[str] = []
    checks = session_input.hit_test_after_move

    def watched(session: Any, element: Any, behavior: Behavior) -> Any:
        check = checks(session, element, behavior)

        def spy(point: tuple[float, float]) -> Any:
            seen.append(main_world_at(cdp, point))
            return check(point)

        return spy

    monkeypatch.setattr(session_input, "hit_test_after_move", watched)

    try:
        hit = live_session.click("#logout")
    except ValueError as refusal:
        # The path crossed the nav and the menu it opened took the point.
        assert not case.must_click, str(refusal)
        assert "covered-after-move" in str(refusal)
        assert seen == ["li|menu-item"]
    else:
        assert hit is not None
        assert seen == [f"{hit.tag}|{hit.class_name}"]
        assert hit.tag in {"a", "span"}

    # The wheel, not the programmatic jump, is what brought the link in, and
    # it left the target clear of the nav rather than flush against its edge.
    assert page.evaluate("() => window.scrollY") != case.start_at
    assert jumped == []
    box = page.evaluate(
        "() => { const r = document.querySelector('#logout')"
        ".getBoundingClientRect();"
        " return [r.top, r.bottom, innerHeight]; }"
    )
    assert box[0] > case.nav_height and box[1] < box[2] - case.nav_height
